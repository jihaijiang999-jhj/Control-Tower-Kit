"""Lint ``tower/workflow@1`` Markdown specs.

The parser is deliberately pure-stdlib: a workflow spec is a document humans
read, so this module reads the same front matter, ``##`` sections and pipe
tables without a YAML or Markdown dependency. It never touches tower state,
the network or any file outside the directory being linted.

Cell escaping
-------------
A table cell may list several states separated by ``|``. Markdown requires the
inner pipes to be escaped as ``\\|``; :func:`split_cells` unescapes them before
:func:`lint_file` splits a ``from``/``to`` cell on ``|`` again.
"""
from __future__ import annotations

import re
from pathlib import Path

SCHEMA = "tower/workflow@1"
REQUIRED_FRONT_MATTER = (
    "schema",
    "id",
    "title",
    "owner",
    "version",
    "enforcement_legend",
)
REQUIRED_SECTIONS = {
    1: "范围",
    2: "状态机",
    3: "转移",
    4: "不变量",
    5: "证据",
    6: "失败模式",
    7: "变更记录",
}

FILE_ID_RE = re.compile(r"^WF-[A-Z]+$")
TR_ID_RE = re.compile(r"^TR-\d+$")
INV_ID_RE = re.compile(r"^INV-\d+$")
FM_ID_RE = re.compile(r"^FM-\d+$")
# A command token is a bare lowercase word (letters, digits, hyphen). Tokens
# such as ``spec_gate=PASS``, ``TASK.md`` or Chinese prose are not commands and
# are skipped by rule 10.
COMMAND_WORD_RE = re.compile(r"^[a-z][a-z0-9-]*$")
SECTION_RE = re.compile(r"^##\s+(\d+)(?:[.．、]|\s)")
TABLE_SEPARATOR_RE = re.compile(r"^\|?[\s:|-]+\|?$")
BACKTICK_TOKEN_RE = re.compile(r"`([^`]+)`")
WILDCARD_STATE = "—"


def unbacktick(value: str) -> str:
    """Strip surrounding whitespace and any backticks from a table cell."""
    return value.strip().strip("`").strip()


def split_cells(line: str) -> list[str]:
    """Split one Markdown table row into trimmed cells.

    Respects ``\\|`` escapes so a cell can contain a literal pipe.
    """
    text = line.strip()
    if text.startswith("|"):
        text = text[1:]
    if text.endswith("|") and not text.endswith("\\|"):
        text = text[:-1]
    cells: list[str] = []
    buf: list[str] = []
    i = 0
    while i < len(text):
        char = text[i]
        if char == "\\" and i + 1 < len(text) and text[i + 1] == "|":
            buf.append("|")
            i += 2
            continue
        if char == "|":
            cells.append("".join(buf).strip())
            buf = []
            i += 1
            continue
        buf.append(char)
        i += 1
    cells.append("".join(buf).strip())
    return cells


def _is_table_row(line: str) -> bool:
    return line.strip().startswith("|")


def _is_separator(line: str) -> bool:
    text = line.strip()
    return "-" in text and bool(TABLE_SEPARATOR_RE.match(text))


def parse_tables(lines: list[str]) -> list[tuple[list[str], list[list[str]]]]:
    """Return ``(header, rows)`` for every pipe table in ``lines``."""
    tables: list[tuple[list[str], list[list[str]]]] = []
    i = 0
    while i < len(lines):
        if (_is_table_row(lines[i]) and i + 1 < len(lines)
                and _is_separator(lines[i + 1])):
            header = split_cells(lines[i])
            rows: list[list[str]] = []
            i += 2
            while i < len(lines) and _is_table_row(lines[i]):
                if _is_separator(lines[i]):
                    i += 1
                    continue
                rows.append(split_cells(lines[i]))
                i += 1
            tables.append((header, rows))
            continue
        i += 1
    return tables


def parse_front_matter(lines: list[str]) -> tuple[dict[str, str], int, list[str]]:
    """Parse the leading ``---`` block.

    Returns ``(fields, body_start, errors)``. When the block is missing or
    unterminated, ``body_start`` still points somewhere safe so the rest of the
    document can be reported on independently.
    """
    errors: list[str] = []
    if not lines or lines[0].strip() != "---":
        errors.append("missing front matter (file must start with '---')")
        return {}, 0, errors
    end = None
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            end = index
            break
    if end is None:
        errors.append("front matter is not terminated by '---'")
        return {}, len(lines), errors
    fields: dict[str, str] = {}
    for line in lines[1:end]:
        if not line.strip() or ":" not in line:
            continue
        key, value = line.split(":", 1)
        fields[key.strip()] = value.strip()
    return fields, end + 1, errors


def parse_sections(lines: list[str]) -> dict[int, list[str]]:
    """Group body lines under their ``## <number>`` heading."""
    sections: dict[int, list[str]] = {}
    current: list[str] | None = None
    for line in lines:
        match = SECTION_RE.match(line)
        if match:
            number = int(match.group(1))
            sections.setdefault(number, [])
            current = sections[number]
            continue
        if line.startswith("## "):
            current = None
            continue
        if current is not None:
            current.append(line)
    return sections


def _legend_values(raw: str) -> list[str]:
    return [unbacktick(value) for value in raw.split("|") if unbacktick(value)]


def _split_states(cell: str) -> list[str]:
    return [unbacktick(part) for part in cell.split("|")]


def lint_file(path: Path, display: str, commands: set[str]) -> dict:
    """Lint one workflow spec file and return its result entry."""
    entry: dict = {
        "path": display,
        "id": "",
        "states": [],
        "transitions": [],
        "invariants": [],
        "failures": [],
        "errors": [],
    }

    def err(message: str) -> None:
        entry["errors"].append(f"{display}: {message}")

    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as exc:
        err(f"cannot read file: {exc}")
        return entry

    lines = text.splitlines()
    fields, body_start, front_errors = parse_front_matter(lines)
    for message in front_errors:
        err(message)

    if fields.get("id"):
        entry["id"] = fields["id"]

    for key in REQUIRED_FRONT_MATTER:
        if not fields.get(key):
            err(f"front matter missing required field: {key}")
    if fields.get("schema") and fields["schema"] != SCHEMA:
        err(f"front matter schema must be {SCHEMA!r}, got {fields['schema']!r}")
    if fields.get("id") and not FILE_ID_RE.match(fields["id"]):
        err(f"front matter id {fields['id']!r} does not match ^WF-[A-Z]+$")
    legend = _legend_values(fields.get("enforcement_legend", ""))
    if fields.get("enforcement_legend") and not legend:
        err("front matter enforcement_legend declares no values")

    sections = parse_sections(lines[body_start:])
    for number, title in REQUIRED_SECTIONS.items():
        if number not in sections:
            err(f"missing required section: ## {number}. {title}")

    # -- rule 4: state table -------------------------------------------------
    states: list[str] = []
    seen_states: set[str] = set()
    state_tables = parse_tables(sections.get(2, []))
    if not state_tables:
        err("section 2: missing state table")
    else:
        for row_no, row in enumerate(state_tables[0][1], 1):
            name = unbacktick(row[0]) if row else ""
            if not name:
                err(f"section 2: empty state name in data row {row_no}")
            elif name in seen_states:
                err(f"section 2: duplicate state {name!r}")
            else:
                seen_states.add(name)
                states.append(name)
        if not states:
            err("section 2: state table declares no states")
    entry["states"] = states

    # -- rules 5, 9, 10: transition table ------------------------------------
    transition_ids: list[str] = []
    seen_transitions: set[str] = set()
    touched_states: set[str] = set()
    transition_tables = parse_tables(sections.get(3, []))
    if not transition_tables:
        err("section 3: missing transition table")
    else:
        for row_no, row in enumerate(transition_tables[0][1], 1):
            if len(row) < 3:
                err(f"section 3: malformed transition row {row_no} (needs ID/from/to)")
                continue
            transition_id = unbacktick(row[0])
            transition_ids.append(transition_id)
            if transition_id in seen_transitions:
                err(f"section 3: duplicate transition id {transition_id!r}")
            seen_transitions.add(transition_id)
            if not TR_ID_RE.match(transition_id):
                err(f"section 3: transition id {transition_id!r} does not match ^TR-\\d+$")
            label = transition_id or f"row {row_no}"
            for column, side in ((1, "from"), (2, "to")):
                cell = row[column] if column < len(row) else ""
                if not cell.strip():
                    err(f"section 3: {label}: empty {side} cell")
                    continue
                for state in _split_states(cell):
                    if not state:
                        err(f"section 3: {label}: empty state in {side} cell")
                        continue
                    touched_states.add(state)
                    if state != WILDCARD_STATE and state not in seen_states:
                        err(f"section 3: {label}: {side} references undeclared state {state!r}")
            if len(row) < 5:
                err(f"section 3: {label}: missing command column")
                continue
            for token in BACKTICK_TOKEN_RE.findall(row[4]):
                token = token.strip()
                if not token:
                    continue
                word = token.split()[0]
                if COMMAND_WORD_RE.match(word) and word not in commands:
                    err(f"section 3: {label}: unknown command {word!r} in command column")
    entry["transitions"] = transition_ids

    # -- rule 6: reachability ------------------------------------------------
    for state in states:
        if state not in touched_states:
            err(f"section 3: declared state {state!r} is unreachable (absent from every from/to)")

    # -- rules 7, 9: invariants ---------------------------------------------
    invariant_ids: list[str] = []
    seen_invariants: set[str] = set()
    invariant_tables = parse_tables(sections.get(4, []))
    if not invariant_tables:
        err("section 4: missing invariant table")
    else:
        for row_no, row in enumerate(invariant_tables[0][1], 1):
            if not row:
                continue
            invariant_id = unbacktick(row[0])
            invariant_ids.append(invariant_id)
            if invariant_id in seen_invariants:
                err(f"section 4: duplicate invariant id {invariant_id!r}")
            seen_invariants.add(invariant_id)
            if not INV_ID_RE.match(invariant_id):
                err(f"section 4: invariant id {invariant_id!r} does not match ^INV-\\d+$")
            if len(row) < 3:
                err(f"section 4: {invariant_id or 'row %d' % row_no}: missing enforcement column")
                continue
            enforcement = unbacktick(row[2])
            if enforcement not in legend:
                err(f"section 4: {invariant_id}: enforcement {enforcement!r} "
                    f"not in enforcement_legend {legend}")
    entry["invariants"] = invariant_ids

    # -- rules 8, 9: failure modes ------------------------------------------
    failure_ids: list[str] = []
    seen_failures: set[str] = set()
    failure_tables = parse_tables(sections.get(6, []))
    if not failure_tables:
        err("section 6: missing failure-mode table")
    else:
        for row in failure_tables[0][1]:
            if not row:
                continue
            failure_id = unbacktick(row[0])
            failure_ids.append(failure_id)
            if failure_id in seen_failures:
                err(f"section 6: duplicate failure id {failure_id!r}")
            seen_failures.add(failure_id)
            if not FM_ID_RE.match(failure_id):
                err(f"section 6: failure id {failure_id!r} does not match ^FM-\\d+$")
    entry["failures"] = failure_ids

    return entry


def _display_path(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.name


def lint_dir(
    directory: Path,
    *,
    root: Path,
    commands: set[str],
    dir_label: str | None = None,
) -> dict:
    """Lint every ``*.md`` file in ``directory`` and return the JSON payload."""
    label = dir_label if dir_label is not None else str(directory)
    result: dict = {"ok": True, "dir": label, "files": [], "errors": []}
    if not directory.is_dir():
        result["ok"] = False
        result["errors"].append(f"specs directory not found: {label}")
        return result
    for path in sorted(directory.glob("*.md")):
        entry = lint_file(path, _display_path(path, root), commands)
        result["files"].append(entry)
        result["errors"].extend(entry["errors"])
    result["ok"] = not result["errors"]
    return result
