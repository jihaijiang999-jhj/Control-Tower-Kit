"""Command layer: STRATEGY/campaign front matter and budgets."""
from __future__ import annotations

import re
from datetime import date, timedelta
from pathlib import Path
from tower_common import TASK_ID_RE, is_safe_id


COMMAND_STRATEGY_REL = "command/STRATEGY.md"


COMMAND_CAMPAIGNS_REL = "command/campaigns"


COMMAND_SCHEMAS = {"strategy": "tower/strategy@1", "campaign": "tower/campaign@1"}


COMMAND_IN_FLIGHT = ("dispatched", "delivered", "reviewed", "accepted")


COMMAND_TERMINAL = ("closed", "aborted")


COMMAND_REVIEW_WINDOW_DAYS = 7


COMMAND_BRIEF_MAX_LINES = 60


COMMAND_BUDGET_CARDS_RE = re.compile(r"(\d+)\s*(?:张卡|cards?)\b", re.IGNORECASE)


COMMAND_BUDGET_WEEKS_RE = re.compile(r"(\d+)\s*(?:周|weeks?)\b", re.IGNORECASE)


COMMAND_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*$")


class CommandDocError(ValueError):
    """A command document is missing, malformed, or outside the YAML subset."""


def command_finding(code: str, target: str, detail: str) -> dict:
    """One E/W finding: ``{code, target, detail}``."""
    return {"code": code, "target": target, "detail": detail}


def command_date(raw) -> date | None:
    """``YYYY-MM-DD`` -> date; anything else -> None (reported by the caller)."""
    try:
        return date.fromisoformat(str(raw or "").strip())
    except ValueError:
        return None


def front_matter_block(text: str) -> list[str]:
    """The lines between the leading and the closing ``---`` fence."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise CommandDocError("front-matter must start on the first line with ---")
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            return lines[1:index]
    raise CommandDocError("front-matter has no closing ---")


def single_quoted_scalar(text: str) -> str:
    """A single-quoted scalar, where ``''`` stands for one literal quote."""
    if len(text) < 2 or not text.endswith("'"):
        raise CommandDocError(f"unterminated single-quoted string: {text!r}")
    body = text[1:-1]
    if "'" in body.replace("''", ""):
        raise CommandDocError(f"unescaped single quote: {text!r}")
    return body.replace("''", "'")


def yaml_scalar(raw: str) -> str:
    """A plain scalar, a single-quoted one, or a double-quoted one.

    Flow syntax (``[...]``/``{...}`` except the empty list, anchors, tags and
    block markers) is rejected: the command layer supports a strict subset.
    """
    text = raw.strip()
    if not text:
        raise CommandDocError("empty value where a scalar is required")
    if text.startswith("'"):
        return single_quoted_scalar(text)
    if text.startswith('"'):
        if len(text) < 2 or not text.endswith('"'):
            raise CommandDocError(f"unterminated quoted string: {text!r}")
        if '"' in text[1:-1]:
            raise CommandDocError(f"escaped quotes are unsupported: {text!r}")
        return text[1:-1]
    if text[0] in "[{&*!|>%@`" or text.endswith('"') or text.endswith("'"):
        raise CommandDocError(f"unsupported scalar syntax: {text!r}")
    return text


def yaml_key_value(text: str, indent: int) -> tuple[str, str]:
    """Split ``key: value`` at ``indent`` spaces; reject anything else."""
    if text[:indent].strip():
        raise CommandDocError(f"unexpected indentation: {text!r}")
    body = text[indent:]
    if ":" not in body:
        raise CommandDocError(f"expected 'key: value': {body!r}")
    key, _, value = body.partition(":")
    key = key.strip()
    if not COMMAND_KEY_RE.match(key):
        raise CommandDocError(f"unsupported key: {key!r}")
    return key, value.strip()


def yaml_mapping_item(rest: str) -> bool:
    """True when a list item body is ``key: value`` rather than a scalar."""
    head = rest.split(":", 1)[0].strip()
    return ":" in rest and bool(COMMAND_KEY_RE.match(head))


def yaml_mapping_entry(lines: list[str], index: int,
                       head: str) -> tuple[dict, int]:
    """Parse ``- key: value`` plus its 4-space continuation keys."""
    key, value = yaml_key_value(head, 0)
    item = {key: yaml_scalar(value)}
    index += 1
    while index < len(lines):
        line = lines[index]
        if not line.strip() or line.lstrip().startswith("#"):
            index += 1
            continue
        if line.startswith("     "):
            raise CommandDocError(f"unsupported nested structure: {line.strip()!r}")
        if not line.startswith("    "):
            break
        key, value = yaml_key_value(line, 4)
        if key in item:
            raise CommandDocError(f"duplicate key in mapping item: {key}")
        item[key] = yaml_scalar(value)
        index += 1
    return item, index


def yaml_list_block(lines: list[str], start: int) -> tuple[list, int]:
    """Parse the 2-space list that follows a bare ``key:``."""
    entries: list = []
    index = start
    mode: bool | None = None
    while index < len(lines):
        line = lines[index]
        if not line.strip() or line.lstrip().startswith("#"):
            index += 1
            continue
        if not line.startswith("  - "):
            break
        body = line[4:]
        mapping = yaml_mapping_item(body)
        if mode is None:
            mode = mapping
        elif mode is not mapping:
            raise CommandDocError("mixed scalar and mapping list items are unsupported")
        if mapping:
            entry, index = yaml_mapping_entry(lines, index, body)
            entries.append(entry)
            continue
        entries.append(yaml_scalar(body))
        index += 1
    return entries, index


def parse_command_front_matter(lines: list[str]) -> dict:
    """Parse front-matter lines into one mapping (supported subset only)."""
    data: dict = {}
    index = 0
    while index < len(lines):
        line = lines[index]
        if not line.strip() or line.lstrip().startswith("#"):
            index += 1
            continue
        if line[0].isspace():
            raise CommandDocError(f"unexpected indentation: {line!r}")
        key, value = yaml_key_value(line, 0)
        if key in data:
            raise CommandDocError(f"duplicate key: {key}")
        if value == "[]":
            data[key] = []
            index += 1
            continue
        if value:
            data[key] = yaml_scalar(value)
            index += 1
            continue
        # An empty key and an explicit ``[]`` are both the empty list; callers
        # that need one element say so (e.g. strategy goals stay E1).
        data[key], index = yaml_list_block(lines, index + 1)
    return data


def load_command_doc(root: Path, relpath: str) -> tuple[dict, str]:
    """Read one command document: its front-matter mapping and full text."""
    path = root / relpath
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise CommandDocError(f"{relpath}: unreadable ({exc.__class__.__name__})") from None
    try:
        return parse_command_front_matter(front_matter_block(text)), text
    except CommandDocError as exc:
        raise CommandDocError(f"{relpath}: {exc}") from None


def command_doc_meta(root: Path, relpath: str, schema: str) -> dict:
    """Load one document and require its declared schema."""
    meta, _ = load_command_doc(root, relpath)
    if meta.get("schema") != schema:
        raise CommandDocError(f"{relpath}: schema must be {schema}")
    return meta


def campaign_relpaths(root: Path) -> list[str]:
    """Tower-relative paths of every ``command/campaigns/*.md`` document."""
    base = root / COMMAND_CAMPAIGNS_REL
    if not base.is_dir():
        return []
    return sorted(path.relative_to(root).as_posix()
                  for path in base.glob("*.md") if path.is_file())


def scalar_items(raw) -> list[str]:
    """A YAML list of non-empty strings; anything else yields nothing."""
    if not isinstance(raw, list):
        return []
    return [str(item) for item in raw if isinstance(item, str) and item.strip()]


def task_force_ids(meta: dict) -> list[str]:
    """The card ids a campaign forces."""
    return scalar_items(meta.get("task_forces"))


def budget_card_limit(raw) -> int | None:
    """The card allowance parsed out of a free-form ``budget`` string."""
    match = COMMAND_BUDGET_CARDS_RE.search(str(raw or ""))
    return int(match.group(1)) if match else None


def budget_week_limit(raw) -> int | None:
    """The week window parsed out of a free-form ``budget`` string."""
    match = COMMAND_BUDGET_WEEKS_RE.search(str(raw or ""))
    return int(match.group(1)) if match else None


def campaign_started(meta: dict) -> date | None:
    """The campaign's optional ``started`` date, when it is well-formed."""
    return command_date(meta.get("started"))


def budget_window_warnings(campaigns: list[dict], today: date) -> list[dict]:
    """W2: ``started`` plus the budget's week window is already in the past.

    A campaign without a parseable ``started``/week window is *not* warned
    about: silence is correct when the deadline cannot be computed.
    """
    warnings: list[dict] = []
    for doc in campaigns:
        if doc.get("status") in COMMAND_TERMINAL:
            continue
        weeks = budget_week_limit(doc.get("budget"))
        started = campaign_started(doc)
        if weeks is None or started is None:
            continue
        if today > started + timedelta(weeks=weeks):
            warnings.append(command_finding(
                "W2", str(doc.get("id") or doc["_path"]),
                f"budget window of {weeks} weeks from {started.isoformat()} "
                "has elapsed"))
    return warnings


def spec_only_warnings(root: Path, campaigns: list[dict]) -> list[dict]:
    """W3: a forced card has a pilot spec but no ``tasks/<id>/`` yet.

    E5 keeps its narrower meaning (neither a task dir nor a spec exists), so a
    spec-only reference is a warning rather than an error.
    """
    warnings: list[dict] = []
    for doc in campaigns:
        for task_id in task_force_ids(doc):
            if not is_safe_id(task_id, TASK_ID_RE):
                continue
            if (root / "tasks" / task_id).is_dir():
                continue
            if (root / "pilot" / f"{task_id}.spec.json").is_file():
                warnings.append(command_finding(
                    "W3", str(doc.get("id") or doc["_path"]),
                    f"task_forces references a spec-only card "
                    f"(no tasks/{task_id}/): {task_id}"))
    return warnings


def command_card_exists(root: Path, task_id: str) -> bool:
    """A reference is real when the card has a record dir or a pilot spec."""
    if not is_safe_id(task_id, TASK_ID_RE):
        return False
    return ((root / "tasks" / task_id).is_dir()
            or (root / "pilot" / f"{task_id}.spec.json").is_file())
