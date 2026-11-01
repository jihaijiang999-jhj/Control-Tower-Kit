"""PILOT-057 probe: exercise the id registry end to end and print evidence.

Fixtures only: every tower root is created under ``scratch/tmp`` (never the real
tower).  The real tower is touched read-only through ``scan_task_ids`` to show
what ``task-ids-init`` will backfill after merge.

    python -B scratch/registry_probe.py
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

WORKTREE = Path(__file__).resolve().parents[1]
TOWER = WORKTREE / "tower-dsh"
TCLI = TOWER / "tools" / "towerctl.py"
REAL_TOWER = Path(r"C:\Users\mac\Documents\deepseek-harness\default-workspace\tower-dsh")
TMP = Path(__file__).resolve().parent / "tmp"
SCHEMA = "tower/task-ids@1"
REGISTRY = "state/TASK_IDS.json"
STAMP = "2026-10-01T00:00:00+08:00"
CHECKS: list[tuple[bool, str]] = []


def cli(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-B", str(TCLI), "--root", str(root), *args],
        capture_output=True, text=True, encoding="utf-8")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check(ok: bool, label: str) -> None:
    CHECKS.append((bool(ok), label))
    print(f"{'PASS' if ok else 'FAIL'}  {label}")


def say(title: str) -> None:
    print(f"\n== {title} ==")


def spec(root: Path, tid: str, title: str) -> None:
    data = {
        "schema": "tower/spec@2", "id": tid, "title": title,
        "authority": "workspace_write", "scope": ["probe the registry"],
        "worktree": f"pilot/worktrees/{tid}",
        "allowed_paths": ["tools/example.py"],
        "forbidden": ["merge", "production access"], "acceptance": ["tests pass"],
        "objective": {
            "problem": "a task id can be reused once its card is archived",
            "outcome": "every used or reserved id is refused by task-new",
            "approach": "registry + init backfill + reserve + close/check hooks",
            "non_goals_and_done": "no id service; done when every gate is green",
        },
    }
    path = root / "specs" / f"{tid}.spec.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    (root / "pilot" / "worktrees" / tid).mkdir(parents=True, exist_ok=True)


def card(root: Path, tid: str, status: str, suffix: str = "") -> None:
    tdir = root / "tasks" / f"{tid}{suffix}"
    tdir.mkdir(parents=True, exist_ok=True)
    record = {"schema": "tower/task@1", "id": tid,
              "title": f"{tid} card {suffix or 'main'}", "status": status,
              "spec_path": f"pilot/{tid}.spec.json",
              "created_at": STAMP, "updated_at": STAMP}
    (tdir / "record.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def tower(name: str) -> Path:
    root = TMP / name
    shutil.rmtree(root, ignore_errors=True)
    for folder in ("primary", "ledger", "specs", "tasks", "state"):
        (root / folder).mkdir(parents=True, exist_ok=True)
    return root


def registry(root: Path) -> dict:
    return json.loads((root / REGISTRY).read_text(encoding="utf-8"))


def snapshot(root: Path) -> dict[str, bytes]:
    found = {}
    for base in ("tasks", "primary", "ledger", "state"):
        for path in sorted((root / base).rglob("*")):
            if path.is_file():
                found[f"{base}/{path.relative_to(root / base).as_posix()}"] = \
                    path.read_bytes()
    return found


def main() -> int:
    shutil.rmtree(TMP, ignore_errors=True)
    TMP.mkdir(parents=True)

    say("1. task-ids-init backfills 055-style tower (VOID dirs, dedupe, stable)")
    root = tower("init")
    for tid, status, suffix in (("PILOT-001", "closed", ""),
                                ("PILOT-002", "delivered", ""),
                                ("PILOT-002", "ready", "-VOID"),
                                ("PILOT-003", "dispatched", "-VOID2"),
                                ("PILOT-004", "closed", ""),
                                ("PILOT-004", "ready", "-VOID")):
        card(root, tid, status, suffix)
    cp = cli(root, "task-ids-init")
    print(cp.stdout.strip())
    ids = registry(root)["ids"]
    check(cp.returncode == 0, "init exit 0")
    check(sorted(ids) == ["PILOT-001", "PILOT-002", "PILOT-003", "PILOT-004"],
          "one entry per id (VOID dirs deduped)")
    check(ids["PILOT-001"]["status"] == "closed", "closed card -> closed")
    check(ids["PILOT-002"]["status"] == "active", "canonical card beats -VOID")
    check(ids["PILOT-003"]["status"] == "void", "VOID-only id -> void")
    check(ids["PILOT-004"]["status"] == "closed", "closed card beats -VOID")
    before = (root / REGISTRY).read_bytes()
    cp = cli(root, "task-ids-init")
    check(cp.returncode == 0 and json.loads(cp.stdout)["added"] == 0,
          "second init adds nothing")
    check((root / REGISTRY).read_bytes() == before, "second init is byte-stable")

    say("2. task-new registers active, close flips it to closed")
    root = tower("active")
    card(root, "PILOT-001", "closed")
    cli(root, "task-ids-init")
    spec(root, "PILOT-057", "registry probe")
    cp = cli(root, "task-new", "--spec", "specs/PILOT-057.spec.json")
    print(cp.stdout.strip())
    entry = registry(root)["ids"]["PILOT-057"]
    check(cp.returncode == 0, "task-new 057 exit 0")
    check(entry["status"] == "active", "task-new registers active")
    check(entry["title"] == "registry probe", "registry keeps the spec title")
    evidence = root / "tasks" / "PILOT-057" / "evidence" / "proof.txt"
    evidence.write_text("proof\n", encoding="utf-8")
    record_path = root / "tasks" / "PILOT-057" / "record.json"
    record = json.loads(record_path.read_text(encoding="utf-8"))
    record.update({
        "status": "accepted", "executor": "exec-probe",
        "review": {"reviewer": "rev-probe", "verdict": "PASS"},
        "decision": {"id": "D-PROBE"},
        "evidence": [{"path": "tasks/PILOT-057/evidence/proof.txt",
                      "sha256": sha256(evidence)}]})
    record_path.write_text(json.dumps(record, ensure_ascii=False, indent=2),
                           encoding="utf-8")
    cp = cli(root, "close", "--task", "PILOT-057")
    print(cp.stdout.strip())
    check(cp.returncode == 0, "close exit 0")
    check(registry(root)["ids"]["PILOT-057"]["status"] == "closed",
          "close flips the registry entry to closed")

    say("3. task-new refuses 057/055/043-style ids with zero writes")
    root = TMP / "active"
    shutil.rmtree(root / "tasks" / "PILOT-057")  # archived card keeps its id
    card(root, "PILOT-055", "dispatched", "-VOID")
    cli(root, "task-ids-init")
    cli(root, "task-ids-reserve", "--id", "PILOT-043", "--title", "reserved 043")
    print("057 (card archived):", registry(root)["ids"]["PILOT-057"]["status"],
          "| 055:", registry(root)["ids"]["PILOT-055"]["status"],
          "| 043:", registry(root)["ids"]["PILOT-043"]["status"])
    spec(root, "PILOT-070", "another draft")
    before = snapshot(root)
    attempts = []
    for tid in ("PILOT-057", "PILOT-055", "PILOT-043"):
        spec(root, tid, f"{tid} reuse")
        cp = cli(root, "task-new", "--spec", f"specs/{tid}.spec.json")
        payload = json.loads(cp.stdout)
        attempts.append((tid, cp.returncode, payload["errors"][0]))
    for tid, code, error in attempts:
        print(f"{tid}: exit {code} {error}")
    check(all(code == 2 for _, code, _ in attempts), "all three exit 2")
    check(all("already registered" in error for _, _, error in attempts),
          "all three say 'already registered'")
    after = snapshot(root)
    changed = [key for key in set(before) | set(after) if before.get(key) != after.get(key)]
    check(not changed, f"tasks/primary/ledger/state unchanged ({changed})")

    say("4. task-ids-reserve holds a draft; reuse is refused")
    root = tower("reserve")
    cp = cli(root, "task-ids-reserve", "--id", "PILOT-056",
             "--title", "towerctl module split", "--spec", "pilot/PILOT-056.spec.json")
    print(cp.stdout.strip())
    entry = registry(root)["ids"]["PILOT-056"]
    check(cp.returncode == 0, "reserve 056 exit 0")
    check(entry["status"] == "reserved", "reserved status recorded")
    before = (root / REGISTRY).read_bytes()
    cp = cli(root, "task-ids-reserve", "--id", "PILOT-056", "--title", "again")
    check(cp.returncode == 2 and "already registered" in cp.stdout,
          "second reserve exit 2")
    check((root / REGISTRY).read_bytes() == before, "registry unchanged")
    spec(root, "PILOT-056", "draft card")
    cp = cli(root, "task-new", "--spec", "specs/PILOT-056.spec.json")
    check(cp.returncode == 2 and "already registered" in cp.stdout,
          "task-new on a reserved id exits 2")
    check(not (root / "tasks" / "PILOT-056").exists(), "no card written")
    check((root / REGISTRY).read_bytes() == before, "registry still unchanged")

    say("5. check --phase spec: id must be registered under the same title")
    root = tower("check")
    spec(root, "PILOT-090", "checked title")
    tdir = root / "tasks" / "PILOT-090"
    tdir.mkdir(parents=True, exist_ok=True)
    record = {"schema": "tower/task@1", "id": "PILOT-090", "title": "checked title",
              "status": "ready", "authority": "workspace_write", "scope": ["x"],
              "allowed_paths": ["tools/example.py"],
              "forbidden": ["merge", "production access"], "acceptance": ["t"],
              "depends_on": [], "worktree": "pilot/worktrees/PILOT-090",
              "spec_path": "specs/PILOT-090.spec.json",
              "spec_sha256": sha256(root / "specs" / "PILOT-090.spec.json"),
              "spec_gate": None, "executor": None, "dispatch": None,
              "evidence": [], "review": None, "decision": None, "closeout": None,
              "created_at": STAMP, "updated_at": STAMP, "next": ""}
    (tdir / "record.json").write_text(json.dumps(record, ensure_ascii=False, indent=2),
                                      encoding="utf-8")
    (tdir / "TASK.md").write_text("# PILOT-090\n", encoding="utf-8")
    (root / "ledger" / "primary.jsonl").write_text(json.dumps(
        {"seq": 1, "at": STAMP, "type": "SPEC_APPROVED", "actor": "rev-probe",
         "payload": {"task": "PILOT-090", "by": "rev-probe"}}) + "\n",
        encoding="utf-8")
    (root / REGISTRY).write_text(json.dumps({"schema": SCHEMA, "ids": {}}) + "\n",
                                 encoding="utf-8")
    cp = cli(root, "check", "--task", "PILOT-090", "--phase", "spec")
    check(cp.returncode == 2 and "not registered" in cp.stdout,
          "unregistered id -> exit 2")
    ids = {"PILOT-090": {"title": "other title", "status": "active",
                         "spec_path": "specs/PILOT-090.spec.json",
                         "created_at": STAMP, "updated_at": STAMP}}
    (root / REGISTRY).write_text(json.dumps({"schema": SCHEMA, "ids": ids},
                                            ensure_ascii=False) + "\n",
                                 encoding="utf-8")
    cp = cli(root, "check", "--task", "PILOT-090", "--phase", "spec")
    check(cp.returncode == 2 and "title mismatch" in cp.stdout,
          "title mismatch -> exit 2")
    ids["PILOT-090"]["title"] = "checked title"
    (root / REGISTRY).write_text(json.dumps({"schema": SCHEMA, "ids": ids},
                                            ensure_ascii=False) + "\n",
                                 encoding="utf-8")
    cp = cli(root, "check", "--task", "PILOT-090", "--phase", "spec")
    check(cp.returncode == 0, "registered + matching title -> exit 0")

    say("6. a missing registry is bootstrapped by task-new (legacy fixtures)")
    root = tower("bootstrap")
    card(root, "PILOT-010", "closed")
    spec(root, "PILOT-011", "bootstrap card")
    check(not (root / REGISTRY).exists(), "registry absent before task-new")
    cp = cli(root, "task-new", "--spec", "specs/PILOT-011.spec.json")
    check(cp.returncode == 0, "task-new exit 0 without a registry")
    ids = registry(root)["ids"]
    check(sorted(ids) == ["PILOT-010", "PILOT-011"], "legacy card + new id both registered")
    check(ids["PILOT-010"]["status"] == "closed", "legacy card keeps closed")
    check(ids["PILOT-011"]["status"] == "active", "new card registers active")
    root = tower("empty")
    spec(root, "PILOT-012", "empty tower card")
    cp = cli(root, "task-new", "--spec", "specs/PILOT-012.spec.json")
    check(cp.returncode == 0 and sorted(registry(root)["ids"]) == ["PILOT-012"],
          "empty tower gets a one-entry registry")

    say("7. real tower scan (read-only; no init, no writes)")
    sys.path.insert(0, str(TOWER / "tools"))
    import towerctl  # noqa: E402  (tools/ must be on sys.path first)
    scanned = towerctl.scan_task_ids(REAL_TOWER)
    statuses: dict[str, int] = {}
    for item in scanned.values():
        statuses[item["status"]] = statuses.get(item["status"], 0) + 1
    print(f"real tower ids={len(scanned)} statuses={statuses}")
    print("043:", scanned.get("PILOT-043", {}).get("status"),
          "| 055:", scanned.get("PILOT-055", {}).get("status"),
          "| 056:", "absent" if "PILOT-056" not in scanned else "present")
    check(len(scanned) >= 55 and set(scanned) >= {f"PILOT-{i:03d}" for i in range(1, 56)},
          "real tower has 001-055 at least")

    failed = [label for ok, label in CHECKS if not ok]
    print(f"\n{len(CHECKS) - len(failed)}/{len(CHECKS)} probe checks passed")
    if failed:
        print("FAILED:", *failed, sep="\n- ")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
