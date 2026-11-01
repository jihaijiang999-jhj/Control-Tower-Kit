"""Profile document, pilot paths and worktree resolution."""
from __future__ import annotations

import re
import shlex
import subprocess
import sys
from pathlib import Path
from tower_common import emit, fail, jload, rel, resolve_input_within
from tower_command import command_date


def load_profile(root: Path) -> dict:
    path = root / "shared" / "PROJECT_PROFILE.json"
    if not path.exists():
        return {}
    try:
        return jload(path)
    except Exception:
        return {}


def _profile_base(root: Path, profile: dict) -> Path:
    """Base for ``pilot.repo`` / ``pilot.worktree`` declared in the profile.

    The profile records the tower root it belongs to; a worktree copy of the
    tower keeps that absolute value, so resolving the declared pilot paths
    against it points at the real pilot instead of the copy.
    """
    declared = profile.get("tower_root")
    if declared:
        try:
            candidate = Path(str(declared))
            if candidate.is_dir():
                return candidate
        except OSError:
            pass
    return root


def _profile_worktree_matches_task(pilot: dict, worktree: str, task_id: str) -> bool:
    """Only use the profile worktree when it belongs to the selected task."""
    if not worktree:
        return False
    if not task_id:
        return True
    declared_task = str(pilot.get("task") or "").strip()
    if declared_task:
        return declared_task == task_id
    return Path(worktree).name == task_id


def resolve_pilot_paths(root: Path, record: dict, profile: dict,
                        task_id: str) -> tuple[Path | None, Path | None]:
    """Resolve the pilot repo and worktree for the selected task.

    ``PROJECT_PROFILE.pilot.repo`` / ``pilot.worktree`` win when present.  The
    profile worktree is only used when it belongs to the selected task;
    otherwise the task's own ``record.worktree`` wins, so a handoff never
    points at another task's worktree.  Missing values fall back to the record
    and finally to the conventional ``pilot/worktrees/<task>`` path.
    """
    pilot = profile.get("pilot") or {}
    profile_base = _profile_base(root, profile)

    repo_value = str(pilot.get("repo") or "").strip()
    repo_base = profile_base
    if not repo_value:
        repo_value = str(record.get("repo") or "").strip()
        repo_base = root
    if not repo_value:
        repo_value = "pilot/repo"
        repo_base = root

    worktree_value = ""
    worktree_base = root
    profile_worktree = str(pilot.get("worktree") or "").strip()
    if _profile_worktree_matches_task(pilot, profile_worktree, task_id):
        worktree_value = profile_worktree
        worktree_base = profile_base
    if not worktree_value:
        worktree_value = str(record.get("worktree") or "").strip()
        worktree_base = root
    if not worktree_value and task_id:
        worktree_value = f"pilot/worktrees/{task_id}"
        worktree_base = root

    def join(base: Path, value: str) -> Path | None:
        if not value:
            return None
        path = Path(value)
        return path if path.is_absolute() else base / path

    return join(repo_base, repo_value), join(worktree_base, worktree_value)


PROFILE_SCHEMA = "tower/profile@1"


PROFILE_REL = "state/PROFILE-TOWER-DSH.md"


PROFILE_STATUSES = ("active", "template")


PROFILE_COLUMNS = ("id", "fact", "probe", "expect", "why")


PROFILE_ID_RE = re.compile(r"^[A-Z0-9-]+$")


PROFILE_SEPARATOR_RE = re.compile(r"^:?-+:?$")


PROFILE_EXPECT_RE = re.compile(r"^exit=(\d+)(?:; stdout=(.+))?$")


PROFILE_PROBE_TIMEOUT = 60


PROFILE_PROBES = (
    "startup", "wiring", "status", "state-verify", "authority-check",
    "verify-ledger", "arch-check", "campaign-check", "shape-check",
    "spec-lint --strict", "spec-coverage", "where --json", "brief")


class ProfileDocError(ValueError):
    """A PROFILE document that cannot be parsed into front-matter plus rows."""


def profile_finding(ident: str, expected: str, actual: str) -> dict:
    return {"id": ident, "expected": expected, "actual": actual}


def profile_meta_value(raw: str) -> str:
    """A front-matter value without its trailing ``# comment``."""
    return raw.split("#", 1)[0].strip()


def profile_front_matter(text: str) -> tuple[dict, list[str]]:
    """Split ``---`` front-matter from the body; every line is ``key: value``."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ProfileDocError("missing front-matter opening '---'")
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() != "---":
            continue
        meta: dict[str, str] = {}
        for offset, raw in enumerate(lines[1:index], start=2):
            stripped = raw.strip()
            if not stripped or stripped.startswith("#"):
                continue
            key, separator, value = stripped.partition(":")
            if not separator or not key.strip():
                raise ProfileDocError(f"bad front-matter line {offset}: {raw!r}")
            meta[key.strip()] = profile_meta_value(value)
        return meta, lines[index + 1:]
    raise ProfileDocError("missing front-matter closing '---'")


def profile_cells(line: str) -> list[str]:
    """The cells of one Markdown table line, outer pipes removed."""
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def profile_table_rows(lines: list[str]) -> list[dict]:
    """The fixed ``id | fact | probe | expect | why`` table, in file order."""
    table = [line.strip() for line in lines if line.strip().startswith("|")]
    if len(table) < 2:
        raise ProfileDocError("PROFILE table is missing (header + separator + rows)")
    if profile_cells(table[0]) != list(PROFILE_COLUMNS):
        raise ProfileDocError(f"table columns must be {list(PROFILE_COLUMNS)}, "
                              f"got {profile_cells(table[0])}")
    if not all(PROFILE_SEPARATOR_RE.match(cell) for cell in profile_cells(table[1])):
        raise ProfileDocError("table separator row is malformed")
    rows: list[dict] = []
    for offset, line in enumerate(table[2:], start=3):
        cells = profile_cells(line)
        if len(cells) != len(PROFILE_COLUMNS):
            raise ProfileDocError(f"table row {offset} must have "
                                  f"{len(PROFILE_COLUMNS)} cells, got {len(cells)}")
        rows.append(dict(zip(PROFILE_COLUMNS, cells), line=offset))
    return rows


def profile_expect(value: str):
    """``(exit_code, stdout_substring|None)`` or ``None`` for bad syntax."""
    match = PROFILE_EXPECT_RE.match(value.strip())
    if match is None:
        return None
    substring = match.group(2)
    if substring is not None and not substring.strip():
        return None
    return int(match.group(1)), substring


def profile_row_findings(row: dict, seen: set[str]) -> list[dict]:
    """One fact row: id, fact, probe whitelist, expect grammar and why."""
    ident = row["id"]
    findings: list[dict] = []
    if not PROFILE_ID_RE.match(ident):
        findings.append(profile_finding(ident or f"line {row['line']}",
                                        "id matches ^[A-Z0-9-]+$", ident))
    elif ident in seen:
        findings.append(profile_finding(ident, "unique id", ident))
    else:
        seen.add(ident)
    for field in ("fact", "why"):
        if not row[field].strip():
            findings.append(profile_finding(ident, f"non-empty {field}", ""))
    if row["probe"] not in PROFILE_PROBES:
        findings.append(profile_finding(ident, "whitelisted read-only probe",
                                        row["probe"]))
    if profile_expect(row["expect"]) is None:
        findings.append(profile_finding(
            ident, "expect: exit=N[; stdout=substring]", row["expect"]))
    return findings


def profile_meta_findings(meta: dict) -> list[dict]:
    """Front-matter schema, required fields, status and updated date."""
    findings: list[dict] = []
    if meta.get("schema") != PROFILE_SCHEMA:
        findings.append(profile_finding("schema", PROFILE_SCHEMA,
                                        str(meta.get("schema"))))
    for field in ("object", "version", "updated", "owner"):
        if not (isinstance(meta.get(field), str) and meta[field].strip()):
            findings.append(profile_finding(field, "non-empty string",
                                            str(meta.get(field))))
    if meta.get("status") not in PROFILE_STATUSES:
        findings.append(profile_finding("status", "|".join(PROFILE_STATUSES),
                                        str(meta.get("status"))))
    if command_date(meta.get("updated")) is None:
        findings.append(profile_finding("updated", "YYYY-MM-DD",
                                        str(meta.get("updated"))))
    return findings


def profile_document_findings(meta: dict, rows: list[dict],
                              requested: str | None) -> list[dict]:
    """Whole-document structure: front-matter, object identity and every row."""
    findings = profile_meta_findings(meta)
    if requested is not None and meta.get("object") != requested:
        findings.append(profile_finding("object", requested,
                                        str(meta.get("object"))))
    seen: set[str] = set()
    for row in rows:
        findings += profile_row_findings(row, seen)
    if meta.get("status") == "active" and not rows:
        findings.append(profile_finding("facts", "at least one fact", "0"))
    return findings


def profile_load(path: Path) -> tuple[dict, list[dict]]:
    """Read and parse one PROFILE; a malformed document raises ProfileDocError."""
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError) as exc:
        raise ProfileDocError(f"cannot read {path}: {exc}") from exc
    meta, body = profile_front_matter(text)
    return meta, profile_table_rows(body)


def profile_select(root: Path, args):
    """``(path, requested_object)`` from ``--file`` / ``--object`` / the default."""
    if args.file and args.object:
        fail(["profile-check: use either --file or --object, not both"])
    if args.object:
        if not PROFILE_ID_RE.match(args.object):
            fail([f"invalid object id: {args.object!r} "
                  f"(must match {PROFILE_ID_RE.pattern})"])
        return root / "state" / f"PROFILE-{args.object}.md", args.object
    if args.file:
        return resolve_input_within(root, args.file, "profile"), None
    return root / PROFILE_REL, None


def profile_run_probe(root: Path, probe: str):
    """Run one whitelisted probe as a child towerctl; ``(exit_code, stdout)``."""
    argv = [sys.executable, "-B",
            str(Path(__file__).resolve().with_name("towerctl.py")),
            "--root", str(root), *shlex.split(probe)]
    try:
        completed = subprocess.run(argv, cwd=str(root), capture_output=True,
                                   text=True, encoding="utf-8", errors="replace",
                                   timeout=PROFILE_PROBE_TIMEOUT)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, f"probe did not run: {exc}"
    return completed.returncode, completed.stdout or ""


def profile_execute(root: Path, row: dict):
    """Run one fact and return a finding, or ``None`` when it holds."""
    code, output = profile_run_probe(root, row["probe"])
    expected_code, substring = profile_expect(row["expect"])
    if code is None:
        return profile_finding(row["id"], row["expect"], output)
    if code != expected_code:
        return profile_finding(row["id"], row["expect"], f"exit={code}")
    if substring is not None and substring not in output:
        return profile_finding(row["id"], row["expect"],
                               f"exit={code}; stdout has no {substring!r}")
    return None


def cmd_profile_check(root: Path, args) -> None:
    """Read-only: parse a PROFILE and run each fact's whitelisted probe."""
    path, requested = profile_select(root, args)
    try:
        meta, rows = profile_load(path)
    except ProfileDocError as exc:
        emit({"ok": False, "object": requested,
              "findings": [profile_finding(rel(root, path), "parseable PROFILE",
                                           str(exc))]}, 2)
    findings = profile_document_findings(meta, rows, requested)
    if findings:
        emit({"ok": False, "object": meta.get("object"), "findings": findings}, 2)
    if meta.get("status") != "active":
        emit({"ok": True, "object": meta.get("object"), "checked": 0,
              "findings": []})
    failures = [item for item in (profile_execute(root, row) for row in rows)
                if item is not None]
    if failures:
        emit({"ok": False, "object": meta.get("object"),
              "checked": len(rows) - len(failures), "findings": failures}, 2)
    emit({"ok": True, "object": meta.get("object"), "checked": len(rows),
          "findings": []})
