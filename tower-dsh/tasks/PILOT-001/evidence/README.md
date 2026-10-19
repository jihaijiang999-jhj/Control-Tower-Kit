# Ledger Chain (PILOT-001)

`ledger_chain` is a small, dependency-free append-only ledger implemented with the Python standard library: each event is stored as one JSON object per line (JSONL), and every record carries a monotonically increasing `seq`, an ISO 8601 `at` timestamp, a caller-supplied `type`, an arbitrary JSON `payload`, the previous record's `hash` (or the literal `"GENESIS"` for the first record) and a `hash` computed as the SHA-256 digest of the canonical JSON encoding — `json.dumps(..., sort_keys=True, separators=(",", ":"), ensure_ascii=False)` encoded as UTF-8 — of all record fields except `hash` itself, so editing any covered field, breaking the `seq` sequence or breaking the `prev_hash` link is detected when the chain is verified.

## Interface

`ledger_chain.append_event(path, event) -> dict`

- Reads the existing JSONL chain at `path` (created on demand, including missing parent directories).
- Assigns `seq` (`1, 2, 3, ...`) and `prev_hash` (`"GENESIS"` first, else the previous record's `hash`); caller-supplied `seq`/`prev_hash` are overwritten.
- Adds `at` only when the event does not already carry a non-null one.
- Appends exactly one canonical JSON line, preserves any extra event fields, and returns the written record. Raises `ValueError` if the chain is already corrupt or the event lacks `type`/`payload`.

`ledger_chain.verify_chain(path) -> {"ok": bool, "count": int, "errors": [{"code", "seq", "message"}]}`

- Parses each non-blank line and checks `seq` is `1..N` in order with no gaps or duplicates, `prev_hash` chains to the previous record's `hash` (`"GENESIS"` first), and the stored `hash` matches the recomputed hash (`MISSING_FIELD` is reported when a required field is absent).
- Error codes: `JSON_INVALID`, `SEQ_GAP`, `PREV_HASH_MISMATCH`, `HASH_MISMATCH`, `MISSING_FIELD`.
- A missing or empty file is a valid empty chain (`ok=True`, `count=0`); repair is out of scope, callers decide what to do with a failed chain.
- Read-only: verification never rewrites the file.

Helpers: `sha256(text)` returns the hex digest of UTF-8 text, `canonical_json(value)` exposes the canonical encoder, and `record_hash(record)` recomputes a record's hash.

## Tests

```console
python -m unittest discover -s tests -v
```
