"""Lint ``tower/workflow@1`` specs and ``tower/policy@1`` documents.

The parser is deliberately pure-stdlib: a workflow spec or a policy document is
something humans read, so this module reads the same front matter, ``##``
sections and pipe tables without a YAML or Markdown dependency. It never
touches tower state, the network or any file outside the directory being
linted.

Two schemas are understood:

* ``tower/workflow@1`` -- state machine, transitions, invariants and failure
  modes (``specs/*.md``).
* ``tower/policy@1`` -- scoped clauses, enforcement levels and failure modes
  (``RED-LINES.md``, ``CHANGE-LEVELS.md`` and policy files under ``specs/``).

By default :func:`lint_root` scans ``<root>/specs/*.md`` and every
``<root>/*.md`` whose front matter declares ``tower/policy@1``. Files at the
root with any other schema are skipped; a non-policy Markdown file in
``specs/`` is still treated as a workflow so its schema mismatch is reported.

Strict mode (``--strict``) is opt-in and adds structural checks that the
tolerant default deliberately skips: table row widths, tables interrupted by a
blank line, duplicate ``## N.`` section numbers and bare ASCII command tokens
in the command column. Chinese prose in the command column is explanatory text,
not a command, and passes strict mode.

Cell escaping
-------------
A table cell may list several states separated by ``|``. Markdown requires the
inner pipes to be escaped as ``\\|``; :func:`split_cells` unescapes them before
:func:`lint_file` splits a ``from``/``to`` cell on ``|`` again.
"""
from __future__ import annotations

import re
from pathlib import Path

WORKFLOW_SCHEMA = "tower/workflow@1"
POLICY_SCHEMA = "tower/policy@1"
SCHEMA = WORKFLOW_SCHEMA
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
POLICY_REQUIRED_SECTIONS = {
    1: "范围",
    2: "条款",
    3: "证据",
    4: "失败模式",
    5: "变更记录",
}
POLICY_CLAUSE_HEADER = ("ID", "条款", "级别", "enforcement", "判定方法")
POLICY_LEVELS = frozenset({"MUST", "MUST NOT", "SHOULD", "SHOULD NOT", "MAY"})

FILE_ID_RE = re.compile(r"^WF-[A-Z]+$")
POLICY_ID_RE = re.compile(r"^POL-[A-Z-]+$")
TR_ID_RE = re.compile(r"^TR-\d+$")
INV_ID_RE = re.compile(r"^INV-\d+$")
FM_ID_RE = re.compile(r"^FM-\d+$")
CLAUSE_ID_RE = re.compile(r"^C-\d+$")
# A command token is a bare lowercase word (letters, digits, hyphen). Tokens
# such as ``spec_gate=PASS``, ``TASK.md`` or Chinese prose are not commands and
# are skipped by rule 10.
COMMAND_WORD_RE = re.compile(r"^[a-z][a-z0-9-]*$")
# Strict mode only rejects a bare (un-backticked) ASCII command-style token.
# Chinese prose such as "任意写事件命令" is documentation, not a command.
BARE_COMMAND_RE = re.compile(r"^[a-z][a-z0-9-]+$")
SECTION_RE = re.compile(r"^##\s+(\d+)(?:[.．、]|\s)")
SECTION_HEADING_RE = re.compile(r"^##\s+(\d+)\.\s*(.*?)\s*$")
TABLE_SEPARATOR_RE = re.compile(r"^\|?[\s:|-]+\|?$")
BACKTICK_TOKEN_RE = re.compile(r"`([^`]+)`")
WILDCARD_STATE = "—"
TOWERCTL = "towerctl"


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


def parse_section_blocks(lines: list[str]) -> list[tuple[int, str, list[str]]]:
    """Return ``(number, title, body_lines)`` for every ``## N. title`` block."""
    blocks: list[tuple[int, str, list[str]]] = []
    current: list[str] | None = None
    for line in lines:
        match = SECTION_HEADING_RE.match(line)
        if match:
            body: list[str] = []
            blocks.append((int(match.group(1)), match.group(2).strip(), body))
            current = body
            continue
        if line.startswith("## "):
            current = None
            continue
        if current is not None:
            current.append(line)
    return blocks


def _legend_values(raw: str) -> list[str]:
    return [unbacktick(value) for value in raw.split("|") if unbacktick(value)]


def bare_command_tokens(cell: str) -> list[str]:
    """Return un-backticked ASCII tokens that look like a command.

    Backticked tokens are stripped first, so ``\\`task-new\\``` and
    ``\\`towerctl spec-lint\\``` produce nothing here. Only whole
    whitespace-separated tokens matching ``^[a-z][a-z0-9-]+$`` are returned;
    Chinese explanatory text and the ``—`` wildcard never match.
    """
    outside = BACKTICK_TOKEN_RE.sub(" ", cell)
    return [token for token in outside.split() if BARE_COMMAND_RE.match(token)]


def _split_states(cell: str) -> list[str]:
    return [unbacktick(part) for part in cell.split("|")]


# ---------------------------------------------------------------------------
# strict checks (opt-in)
# ---------------------------------------------------------------------------
def _strict_table_errors(lines: list[str]) -> list[str]:
    """Column-width and blank-line-interruption checks for every table."""
    errors: list[str] = []
    i = 0
    while i < len(lines):
        if not (_is_table_row(lines[i]) and i + 1 < len(lines)
                and _is_separator(lines[i + 1])):
            i += 1
            continue
        start_line = i + 1
        expected = len(split_cells(lines[i]))
        i += 2
        while i < len(lines):
            current = lines[i]
            if _is_table_row(current):
                if _is_separator(current):
                    i += 1
                    continue
                actual = len(split_cells(current))
                if actual != expected:
                    errors.append(
                        f"table starting at line {start_line}: row {i + 1} has "
                        f"{actual} cells, expected {expected}")
                i += 1
                continue
            if not current.strip():
                lookahead = i
                while lookahead < len(lines) and not lines[lookahead].strip():
                    lookahead += 1
                first_blank = i == 0 or bool(lines[i - 1].strip())
                if (first_blank and lookahead < len(lines)
                        and _is_table_row(lines[lookahead])):
                    errors.append(
                        f"table interrupted by blank line after line {i} "
                        f"(table starting at line {start_line})")
            break
        # Fall through: the outer loop keeps scanning from the current line.
    return errors


def _strict_duplicate_section_errors(lines: list[str]) -> list[str]:
    """Report a ``## N.`` section number that appears more than once."""
    errors: list[str] = []
    seen: set[int] = set()
    for line in lines:
        match = SECTION_HEADING_RE.match(line)
        if not match:
            continue
        number = int(match.group(1))
        if number in seen:
            errors.append(f"duplicate section number: ## {number}")
        else:
            seen.add(number)
    return errors


def strict_structure_errors(lines: list[str]) -> list[str]:
    """Structural errors that only ``--strict`` reports."""
    return _strict_table_errors(lines) + _strict_duplicate_section_errors(lines)


# ---------------------------------------------------------------------------
# workflow lint
# ---------------------------------------------------------------------------
def lint_file(
    path: Path,
    display: str,
    commands: set[str],
    *,
    strict: bool = False,
) -> dict:
    """Lint one workflow spec file and return its result entry."""
    entry: dict = {
        "path": display,
        "kind": "workflow",
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
    body = lines[body_start:]
    if strict:
        for message in strict_structure_errors(body):
            err(message)

    if fields.get("id"):
        entry["id"] = fields["id"]

    for key in REQUIRED_FRONT_MATTER:
        if not fields.get(key):
            err(f"front matter missing required field: {key}")
    if fields.get("schema") and fields["schema"] != WORKFLOW_SCHEMA:
        err(f"front matter schema must be {WORKFLOW_SCHEMA!r}, got {fields['schema']!r}")
    if fields.get("id") and not FILE_ID_RE.match(fields["id"]):
        err(f"front matter id {fields['id']!r} does not match ^WF-[A-Z]+$")
    legend = _legend_values(fields.get("enforcement_legend", ""))
    if fields.get("enforcement_legend") and not legend:
        err("front matter enforcement_legend declares no values")

    sections = parse_sections(body)
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
    command_column = 4
    if transition_tables:
        for index, name in enumerate(transition_tables[0][0]):
            if unbacktick(name) == "命令":
                command_column = index
                break
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
            if len(row) <= command_column:
                err(f"section 3: {label}: missing command column")
                continue
            command_cell = row[command_column]
            tokens = [token.strip() for token in BACKTICK_TOKEN_RE.findall(command_cell)
                      if token.strip()]
            for token in tokens:
                parts = token.split()
                word = parts[0]
                if word == TOWERCTL:
                    # ``towerctl <sub>`` is validated by its subcommand; a lone
                    # ``towerctl`` does not name anything to check.
                    if len(parts) < 2:
                        continue
                    word = parts[1]
                if COMMAND_WORD_RE.match(word) and word not in commands:
                    err(f"section 3: {label}: unknown command {word!r} in command column")
            if strict:
                bare = bare_command_tokens(command_cell)
                if bare:
                    err(f"section 3: {label}: command column must be a backtick "
                        f"token, a Chinese description or —, got bare command "
                        f"{bare[0]!r}")
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


# ---------------------------------------------------------------------------
# policy lint
# ---------------------------------------------------------------------------
def lint_policy_file(
    path: Path,
    display: str,
    commands: set[str] | None = None,
    *,
    strict: bool = False,
) -> dict:
    """Lint one ``tower/policy@1`` document and return its result entry."""
    entry: dict = {
        "path": display,
        "kind": "policy",
        "id": "",
        "clauses": [],
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
    body = lines[body_start:]
    if strict:
        for message in strict_structure_errors(body):
            err(message)

    if fields.get("id"):
        entry["id"] = fields["id"]

    for key in REQUIRED_FRONT_MATTER:
        if not fields.get(key):
            err(f"front matter missing required field: {key}")
    if fields.get("schema") and fields["schema"] != POLICY_SCHEMA:
        err(f"front matter schema must be {POLICY_SCHEMA!r}, got {fields['schema']!r}")
    if fields.get("id") and not POLICY_ID_RE.match(fields["id"]):
        err(f"front matter id {fields['id']!r} does not match ^POL-[A-Z-]+$")
    legend = _legend_values(fields.get("enforcement_legend", ""))
    if fields.get("enforcement_legend") and not legend:
        err("front matter enforcement_legend declares no values")

    blocks = parse_section_blocks(body)
    by_number: dict[int, tuple[str, list[str]]] = {}
    for number, title, block in blocks:
        by_number.setdefault(number, (title, block))
    for number, title in POLICY_REQUIRED_SECTIONS.items():
        if number not in by_number:
            err(f"missing required section: ## {number}. {title}")
            continue
        actual, _block = by_number[number]
        if actual != title:
            err(f"section ## {number}. heading must be {title!r}, got {actual!r}")

    # -- section 2: clause table ---------------------------------------------
    clause_ids: list[str] = []
    seen_clauses: set[str] = set()
    if 2 in by_number:
        clause_tables = parse_tables(by_number[2][1])
        if not clause_tables:
            err("section 2: missing clause table")
        else:
            header, rows = clause_tables[0]
            if tuple(header) != POLICY_CLAUSE_HEADER:
                err("section 2: clause table header must be "
                    f"{' | '.join(POLICY_CLAUSE_HEADER)!r}, got {' | '.join(header)!r}")
            for row_no, row in enumerate(rows, 1):
                if not row:
                    continue
                if len(row) < len(POLICY_CLAUSE_HEADER):
                    err(f"section 2: data row {row_no} has {len(row)} cells, "
                        f"expected {len(POLICY_CLAUSE_HEADER)}")
                clause_id = unbacktick(row[0]) if row else ""
                if not clause_id:
                    err(f"section 2: data row {row_no}: empty clause ID")
                else:
                    if clause_id in seen_clauses:
                        err(f"section 2: duplicate clause id {clause_id!r}")
                    seen_clauses.add(clause_id)
                    clause_ids.append(clause_id)
                    if not CLAUSE_ID_RE.match(clause_id):
                        err(f"section 2: clause id {clause_id!r} does not match ^C-\\d+$")
                level = unbacktick(row[2]) if len(row) > 2 else ""
                if level not in POLICY_LEVELS:
                    err(f"section 2: {clause_id or 'row %d' % row_no}: level "
                        f"{level!r} must be one of {', '.join(sorted(POLICY_LEVELS))}")
                enforcement = unbacktick(row[3]) if len(row) > 3 else ""
                if enforcement not in legend:
                    err(f"section 2: {clause_id or 'row %d' % row_no}: enforcement "
                        f"{enforcement!r} not in enforcement_legend {legend}")
                method = row[4] if len(row) > 4 else ""
                if not unbacktick(method):
                    err(f"section 2: {clause_id or 'row %d' % row_no}: "
                        "empty 判定方法 cell")
    entry["clauses"] = clause_ids

    # -- section 4: failure-mode table ---------------------------------------
    failure_ids: list[str] = []
    seen_failures: set[str] = set()
    if 4 in by_number:
        failure_tables = parse_tables(by_number[4][1])
        if not failure_tables:
            err("section 4: missing failure-mode table")
        else:
            for row in failure_tables[0][1]:
                if not row:
                    continue
                failure_id = unbacktick(row[0])
                if failure_id in seen_failures:
                    err(f"section 4: duplicate failure id {failure_id!r}")
                seen_failures.add(failure_id)
                if not FM_ID_RE.match(failure_id):
                    err(f"section 4: failure id {failure_id!r} does not match ^FM-\\d+$")
                else:
                    failure_ids.append(failure_id)
    entry["failures"] = failure_ids

    return entry


# ---------------------------------------------------------------------------
# discovery / dispatch
# ---------------------------------------------------------------------------
def _display_path(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.name


def _front_matter_fields(path: Path) -> dict[str, str]:
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return {}
    fields, _body_start, _errors = parse_front_matter(text.splitlines())
    return fields


def lint_path(
    path: Path,
    display: str,
    commands: set[str],
    *,
    strict: bool = False,
) -> dict:
    """Lint ``path`` with the linter its front matter schema selects."""
    if _front_matter_fields(path).get("schema") == POLICY_SCHEMA:
        return lint_policy_file(path, display, commands, strict=strict)
    return lint_file(path, display, commands, strict=strict)


def lint_dir(
    directory: Path,
    *,
    root: Path,
    commands: set[str],
    dir_label: str | None = None,
    strict: bool = False,
) -> dict:
    """Lint every ``*.md`` file in ``directory`` and return the JSON payload."""
    label = dir_label if dir_label is not None else str(directory)
    result: dict = {"ok": True, "dir": label, "files": [], "errors": []}
    if not directory.is_dir():
        result["ok"] = False
        result["errors"].append(f"specs directory not found: {label}")
        return result
    for path in sorted(directory.glob("*.md")):
        entry = lint_path(path, _display_path(path, root), commands, strict=strict)
        result["files"].append(entry)
        result["errors"].extend(entry["errors"])
    result["ok"] = not result["errors"]
    return result


def lint_root(
    root: Path,
    *,
    commands: set[str],
    strict: bool = False,
) -> dict:
    """Lint the tower root: ``specs/*.md`` plus root-level policy documents.

    Root-level Markdown that does not declare ``tower/policy@1`` is skipped, so
    prose documents such as ``README.md`` are never validated as policies.
    A missing ``specs/`` directory is tolerated here; ``--dir`` remains the
    explicit way to assert that a directory exists.
    """
    result: dict = {"ok": True, "dir": ".", "files": [], "errors": []}
    specs = root / "specs"
    if specs.is_dir():
        for path in sorted(specs.glob("*.md")):
            entry = lint_path(path, _display_path(path, root), commands, strict=strict)
            result["files"].append(entry)
            result["errors"].extend(entry["errors"])
    for path in sorted(root.glob("*.md")):
        if _front_matter_fields(path).get("schema") != POLICY_SCHEMA:
            continue
        entry = lint_policy_file(path, _display_path(path, root), commands, strict=strict)
        result["files"].append(entry)
        result["errors"].extend(entry["errors"])
    result["ok"] = not result["errors"]
    return result
