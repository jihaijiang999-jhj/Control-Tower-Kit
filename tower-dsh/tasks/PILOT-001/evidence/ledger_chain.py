"""Append-only JSONL hash-chain ledger (standard library only).

Each record is one JSON object per line.  A record carries ``seq`` (1-based,
gap-free), ``at`` (ISO 8601), ``type``, ``payload``, ``prev_hash`` and ``hash``.
``hash`` is the SHA-256 of the canonical JSON encoding of the record without
the ``hash`` field itself, so editing any covered field breaks verification.

Canonical encoding is ``json.dumps(..., sort_keys=True,
separators=(",", ":"), ensure_ascii=False)`` encoded as UTF-8.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

GENESIS = "GENESIS"
HASH_FIELD = "hash"
REQUIRED_FIELDS = ("seq", "at", "type", "payload", "prev_hash")


def sha256(text: str) -> str:
    """Return the lowercase hex SHA-256 digest of ``text`` encoded as UTF-8."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def canonical_json(value: object) -> str:
    """Serialize ``value`` to the canonical JSON form used for hashing."""
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def record_hash(record: dict) -> str:
    """Compute the ``hash`` of ``record`` from all fields except ``hash``."""
    body = {key: value for key, value in record.items() if key != HASH_FIELD}
    return sha256(canonical_json(body))


def _iter_payload_lines(path: Path):
    """Yield ``(line_number, raw_line)`` for non-blank lines in ``path``."""
    with path.open("r", encoding="utf-8") as handle:
        for line_number, raw in enumerate(handle, start=1):
            if raw.strip():
                yield line_number, raw


def _load_existing_records(path: Path) -> list:
    """Parse every non-blank line of an existing chain."""
    records = []
    for line_number, raw in _iter_payload_lines(path):
        try:
            record = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"cannot append to a corrupt chain: line {line_number} is not valid JSON ({exc.msg})"
            ) from exc
        if not isinstance(record, dict):
            raise ValueError(
                f"cannot append to a corrupt chain: line {line_number} is not a JSON object"
            )
        records.append(record)
    return records


def _ends_with_newline(path: Path) -> bool:
    """Report whether a non-empty file ends with a newline byte."""
    with path.open("rb") as handle:
        handle.seek(-1, 2)
        return handle.read(1) == b"\n"


def append_event(path, event: dict) -> dict:
    """Append ``event`` to the JSONL chain at ``path`` and return the record.

    ``seq`` and ``prev_hash`` are always assigned by the chain.  An ``at``
    timestamp is added only when the event does not already carry one.  Extra
    event fields are preserved and covered by the hash.
    """
    if not isinstance(event, dict):
        raise TypeError("event must be a JSON-serializable dict")

    target = Path(path)
    seq = 1
    prev_hash = GENESIS

    if target.exists():
        records = _load_existing_records(target)
        if records:
            last = records[-1]
            if not isinstance(last.get("seq"), int) or not isinstance(last.get("hash"), str):
                raise ValueError(
                    "cannot append: the last record is missing a usable seq/hash"
                )
            seq = last["seq"] + 1
            prev_hash = last["hash"]

    record = dict(event)
    record.pop(HASH_FIELD, None)
    record["seq"] = seq
    record["prev_hash"] = prev_hash
    if record.get("at") is None:
        record["at"] = datetime.now(timezone.utc).isoformat()
    if "type" not in record or "payload" not in record:
        raise ValueError("event must contain 'type' and 'payload'")

    record[HASH_FIELD] = record_hash(record)
    line = canonical_json(record)

    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8", newline="\n") as handle:
        if target.stat().st_size > 0 and not _ends_with_newline(target):
            handle.write("\n")
        handle.write(line + "\n")

    return record


def _error(code: str, seq, message: str) -> dict:
    return {"code": code, "seq": seq, "message": message}


def verify_chain(path) -> dict:
    """Verify the JSONL chain at ``path``.

    Returns ``{"ok": bool, "count": int, "errors": [{"code", "seq", "message"}]}``
    where ``count`` is the number of JSON object records parsed.  A missing or
    empty file is an empty but valid chain.
    """
    target = Path(path)
    errors = []
    records = []

    if not target.exists():
        return {"ok": True, "count": 0, "errors": []}

    position = 0
    for line_number, raw in _iter_payload_lines(target):
        position += 1
        try:
            record = json.loads(raw)
        except json.JSONDecodeError as exc:
            errors.append(
                _error(
                    "JSON_INVALID",
                    position,
                    f"line {line_number}: invalid JSON ({exc.msg})",
                )
            )
            continue
        if not isinstance(record, dict):
            errors.append(
                _error(
                    "JSON_INVALID",
                    position,
                    f"line {line_number}: record is not a JSON object",
                )
            )
            continue

        records.append(record)
        seq_value = record.get("seq") if isinstance(record.get("seq"), int) else position
        missing = [name for name in REQUIRED_FIELDS + (HASH_FIELD,) if name not in record]
        if missing:
            errors.append(
                _error(
                    "MISSING_FIELD",
                    seq_value,
                    f"line {line_number}: missing field(s): {', '.join(missing)}",
                )
            )
            continue

        if record["seq"] != position:
            errors.append(
                _error(
                    "SEQ_GAP",
                    record["seq"],
                    f"line {line_number}: expected seq {position}, found {record['seq']!r}",
                )
            )

        if len(records) == 1:
            if record["prev_hash"] != GENESIS:
                errors.append(
                    _error(
                        "PREV_HASH_MISMATCH",
                        record["seq"],
                        f"line {line_number}: first record must have prev_hash {GENESIS!r}",
                    )
                )
        else:
            previous = records[-2]
            if record["prev_hash"] != previous.get("hash"):
                errors.append(
                    _error(
                        "PREV_HASH_MISMATCH",
                        record["seq"],
                        f"line {line_number}: prev_hash does not match the previous record's hash",
                    )
                )

        if record_hash(record) != record["hash"]:
            errors.append(
                _error(
                    "HASH_MISMATCH",
                    record["seq"],
                    f"line {line_number}: recomputed hash does not match the stored hash",
                )
            )

    return {"ok": not errors, "count": len(records), "errors": errors}
