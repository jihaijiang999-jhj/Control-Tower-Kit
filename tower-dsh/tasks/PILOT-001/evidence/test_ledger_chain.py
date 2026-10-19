"""Tests for ``ledger_chain`` (stdlib ``unittest`` only)."""

import hashlib
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import ledger_chain


def expected_hash(record):
    """Independent re-implementation of the documented hashing rule."""
    body = {key: value for key, value in record.items() if key != "hash"}
    canonical = json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class LedgerChainTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "ledger.jsonl"

    # -- helpers ---------------------------------------------------------
    def append_three(self):
        return [
            ledger_chain.append_event(
                self.path, {"type": "created", "payload": {"id": 1, "amount": 10}}
            ),
            ledger_chain.append_event(
                self.path, {"type": "updated", "payload": {"id": 1, "amount": 20}}
            ),
            ledger_chain.append_event(
                self.path, {"type": "closed", "payload": {"id": 1, "amount": 20}}
            ),
        ]

    def read_lines(self):
        return self.path.read_text(encoding="utf-8").splitlines()

    def write_lines(self, lines):
        self.path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def mutate(self, index, mutator):
        lines = self.read_lines()
        record = json.loads(lines[index])
        mutator(record)
        lines[index] = json.dumps(
            record, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )
        self.write_lines(lines)

    def codes(self, result):
        return [error["code"] for error in result["errors"]]

    def assert_ok(self, result, count):
        self.assertTrue(result["ok"], result["errors"])
        self.assertEqual(result["count"], count)
        self.assertEqual(result["errors"], [])

    def assert_error(self, result, code, count=None):
        self.assertFalse(result["ok"])
        self.assertIn(code, self.codes(result))
        if count is not None:
            self.assertEqual(result["count"], count)

    # -- happy path ------------------------------------------------------
    def test_valid_chain_appends_and_verifies(self):
        records = self.append_three()

        self.assertEqual([record["seq"] for record in records], [1, 2, 3])
        self.assertEqual(records[0]["prev_hash"], "GENESIS")
        self.assertEqual(records[1]["prev_hash"], records[0]["hash"])
        self.assertEqual(records[2]["prev_hash"], records[1]["hash"])
        for record in records:
            self.assertEqual(record["hash"], expected_hash(record))

        result = ledger_chain.verify_chain(self.path)
        self.assert_ok(result, 3)

        stored = [json.loads(line) for line in self.read_lines()]
        self.assertEqual(stored, records)
        self.assertEqual([record["seq"] for record in stored], [1, 2, 3])
        self.assertEqual(stored[0]["prev_hash"], "GENESIS")
        self.assertEqual(stored[1]["prev_hash"], stored[0]["hash"])
        self.assertEqual(stored[2]["prev_hash"], stored[1]["hash"])
        for record in stored:
            self.assertEqual(record["hash"], expected_hash(record))
            self.assertEqual(len(record["hash"]), 64)
            self.assertIsNotNone(datetime.fromisoformat(record["at"]).tzinfo)

    def test_at_is_added_only_when_absent(self):
        provided = "2024-01-02T03:04:05+00:00"
        first = ledger_chain.append_event(
            self.path, {"type": "a", "payload": {}, "at": provided}
        )
        second = ledger_chain.append_event(self.path, {"type": "b", "payload": {}})

        self.assertEqual(first["at"], provided)
        self.assertNotEqual(second["at"], provided)
        self.assertIsNotNone(datetime.fromisoformat(second["at"]).tzinfo)
        self.assert_ok(ledger_chain.verify_chain(self.path), 2)

    def test_unicode_payload_is_not_escaped(self):
        record = ledger_chain.append_event(
            self.path, {"type": "note", "payload": {"text": "中文 ✓"}}
        )
        self.assertIn("中文 ✓", self.read_lines()[0])
        self.assertEqual(record["payload"], {"text": "中文 ✓"})
        self.assert_ok(ledger_chain.verify_chain(self.path), 1)

    def test_append_to_file_without_trailing_newline(self):
        ledger_chain.append_event(self.path, {"type": "a", "payload": {}})
        raw = self.path.read_text(encoding="utf-8").rstrip("\n")
        self.path.write_text(raw, encoding="utf-8")

        ledger_chain.append_event(self.path, {"type": "b", "payload": {}})

        self.assertEqual(len(self.read_lines()), 2)
        self.assert_ok(ledger_chain.verify_chain(self.path), 2)

    def test_empty_or_missing_chain_is_valid(self):
        self.assert_ok(ledger_chain.verify_chain(self.path), 0)

        self.path.write_text("\n", encoding="utf-8")
        self.assert_ok(ledger_chain.verify_chain(self.path), 0)

    # -- tamper detection ------------------------------------------------
    def test_content_tamper_detected(self):
        self.append_three()
        self.mutate(1, lambda record: record["payload"].update({"amount": 999}))

        result = ledger_chain.verify_chain(self.path)
        self.assert_error(result, "HASH_MISMATCH", count=3)
        mismatched = [e for e in result["errors"] if e["code"] == "HASH_MISMATCH"]
        self.assertEqual([e["seq"] for e in mismatched], [2])

    def test_prev_hash_tamper_detected(self):
        self.append_three()
        self.mutate(1, lambda record: record.update({"prev_hash": "0" * 64}))

        result = ledger_chain.verify_chain(self.path)
        self.assertFalse(result["ok"])
        self.assertEqual(result["count"], 3)
        self.assertTrue(
            {"PREV_HASH_MISMATCH", "HASH_MISMATCH"} & set(self.codes(result)),
            result["errors"],
        )

    def test_seq_gap_detected(self):
        self.append_three()
        self.mutate(1, lambda record: record.update({"seq": 5}))

        result = ledger_chain.verify_chain(self.path)
        self.assert_error(result, "SEQ_GAP", count=3)
        self.assertEqual(
            [e["seq"] for e in result["errors"] if e["code"] == "SEQ_GAP"], [5]
        )

    def test_duplicate_seq_detected(self):
        self.append_three()
        self.mutate(2, lambda record: record.update({"seq": 2}))

        result = ledger_chain.verify_chain(self.path)
        self.assert_error(result, "SEQ_GAP", count=3)

    def test_hash_tamper_detected(self):
        self.append_three()
        self.mutate(1, lambda record: record.update({"hash": "ab" * 32}))

        result = ledger_chain.verify_chain(self.path)
        self.assert_error(result, "HASH_MISMATCH", count=3)
        mismatched = [e for e in result["errors"] if e["code"] == "HASH_MISMATCH"]
        self.assertEqual([e["seq"] for e in mismatched], [2])

    def test_invalid_json_line_detected(self):
        self.append_three()
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write('{"seq": 4, "broken" \n')

        result = ledger_chain.verify_chain(self.path)
        self.assert_error(result, "JSON_INVALID", count=3)
        self.assertEqual([e["seq"] for e in result["errors"]], [4])

    def test_missing_field_detected(self):
        self.append_three()
        self.mutate(1, lambda record: record.pop("payload"))

        result = ledger_chain.verify_chain(self.path)
        self.assert_error(result, "MISSING_FIELD", count=3)
        self.assertEqual(
            [e["seq"] for e in result["errors"] if e["code"] == "MISSING_FIELD"], [2]
        )

    def test_first_record_must_be_genesis(self):
        self.append_three()
        self.mutate(0, lambda record: record.update({"prev_hash": "not-genesis"}))

        result = ledger_chain.verify_chain(self.path)
        self.assert_error(result, "PREV_HASH_MISMATCH", count=3)

    def test_verification_is_read_only(self):
        self.append_three()
        before = self.path.read_text(encoding="utf-8")
        ledger_chain.verify_chain(self.path)
        self.assertEqual(self.path.read_text(encoding="utf-8"), before)


if __name__ == "__main__":
    unittest.main()
