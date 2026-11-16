"""PILOT-078: the docs keep the 077 close-out numbers (no network, no writes).

The tower has twice shipped a document that contradicted the state (``MAP``
still said 58 tasks after the tower had 65, ``REPRODUCE`` still said 252 tests
after the suite had 844).  This module pins the numbers to files that the
control plane already owns, so a doc drift turns the suite red:

* **76 代码卡** — plain ``tasks/PILOT-0NN`` records with ``NN <= 77``;
* **74 信封** — ``supervision/envelopes/ENV-PILOT-*.json`` whose task is
  ``<= PILOT-077`` (the 078 doc card adds no close-out envelope);
* **844 tests** — ``ENV-PILOT-077.tower_tests_baseline`` (frozen close-out
  count, not the local ``844 + N``);
* **16 张交付卡 / 16-16** — C-04 roadmap nodes other than the 078 doc card;
* **17 节点** — the whole C-04 roadmap, 078 included;
* **gates/events/modules** — ``arch/GATES.json``, ``EVENT_CATALOG.json`` and
  ``tools/tower_*.py``, exactly what ``arch-check`` reads.

It also asserts that ``PILOT-072`` is registered as ``void`` with the parked
spec path, and that ``docs/WALKTHROUGH.md`` exists.  Everything is a plain file
read: no subprocess writes state, no network, no clock.

Run from the tower root (``tower-dsh``)::

    python -B tools/run_tests.py --pattern test_docs_current.py
"""
from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

# tower-dsh/tools/tests/test_docs_current.py -> tower-dsh
TOWER = Path(__file__).resolve().parents[2]
REPO = TOWER.parent

CODE_CARD_LIMIT = 77          # 078 is a doc card, not a code card
DOC_CARD = "PILOT-078"
VOID_CARD = "PILOT-072"
CLOSEOUT_ENVELOPE = "ENV-PILOT-077.json"


def read(path: Path) -> str:
    if not path.is_file():
        raise AssertionError(f"missing required file: {path}")
    return path.read_text(encoding="utf-8")


def load(path: Path) -> dict:
    return json.loads(read(path))


def card_number(task_id: str) -> int:
    match = re.fullmatch(r"PILOT-(\d{3})", task_id)
    if not match:
        raise AssertionError(f"unexpected task id: {task_id!r}")
    return int(match.group(1))


def plain_task_dirs() -> list[Path]:
    return [path for path in (TOWER / "tasks").iterdir()
            if path.is_dir() and re.fullmatch(r"PILOT-\d{3}", path.name)]


def envelope_docs() -> list[dict]:
    return [load(path) for path in
            sorted((TOWER / "supervision" / "envelopes").glob("ENV-PILOT-*.json"))]


def campaign_nodes() -> list[str]:
    text = read(TOWER / "command" / "campaigns" / "C-2026-Q4-04.md")
    block = re.search(r"(?m)^roadmap:\s*\n((?:  - PILOT-\d+\n)+)", text)
    if not block:
        raise AssertionError("C-2026-Q4-04 has no roadmap list")
    return re.findall(r"PILOT-\d+", block.group(1))


class DocNumbersTestCase(unittest.TestCase):
    """77 close-out numbers, derived from state, asserted in the docs."""

    def setUp(self) -> None:
        self.next_window = read(TOWER / "NEXT-WINDOW.md")
        self.readme = read(TOWER / "README.md")
        self.reproduce = read(TOWER / "REPRODUCE.md")
        self.architecture = read(TOWER / "ARCHITECTURE.md")
        self.map_md = read(REPO / "control-tower" / "MAP.md")
        self.walkthrough = read(TOWER / "docs" / "WALKTHROUGH.md")
        self.task_ids = load(TOWER / "state" / "TASK_IDS.json")["ids"]

    # -- derived facts -----------------------------------------------------
    def code_cards(self) -> int:
        return sum(1 for path in plain_task_dirs()
                   if card_number(path.name) <= CODE_CARD_LIMIT)

    def envelopes(self) -> int:
        return sum(1 for env in envelope_docs()
                   if card_number(env["task"]) <= CODE_CARD_LIMIT)

    def closeout_baseline(self) -> int:
        return load(TOWER / "supervision" / "envelopes" / CLOSEOUT_ENVELOPE)[
            "tower_tests_baseline"]

    def delivery_cards(self) -> list[str]:
        return [node for node in campaign_nodes() if node != DOC_CARD]

    # -- 1. the four headline numbers -------------------------------------
    def test_docs_keep_76_code_cards(self) -> None:
        self.assertEqual(self.code_cards(), 76,
                         msg="plain task records <= PILOT-077 must be 76")
        for name, text in (("NEXT-WINDOW.md", self.next_window),
                           ("README.md", self.readme),
                           ("control-tower/MAP.md", self.map_md)):
            self.assertIn("76 代码卡", text, msg=f"{name} lost the 76 code-card count")

    def test_docs_keep_74_envelopes(self) -> None:
        self.assertEqual(self.envelopes(), 74,
                         msg="close-out envelopes (task <= PILOT-077) must be 74")
        for name, text in (("NEXT-WINDOW.md", self.next_window),
                           ("README.md", self.readme),
                           ("control-tower/MAP.md", self.map_md)):
            self.assertIn("74 信封", text, msg=f"{name} lost the 74 envelope count")

    def test_docs_keep_844_tests(self) -> None:
        self.assertEqual(self.closeout_baseline(), 844,
                         msg="ENV-PILOT-077.tower_tests_baseline must stay 844")
        for name, text in (("NEXT-WINDOW.md", self.next_window),
                           ("README.md", self.readme),
                           ("REPRODUCE.md", self.reproduce),
                           ("control-tower/MAP.md", self.map_md)):
            self.assertIn(str(self.closeout_baseline()), text,
                          msg=f"{name} no longer names the 844 close-out baseline")

    def test_docs_keep_16_delivery_cards(self) -> None:
        delivery = self.delivery_cards()
        self.assertEqual(len(delivery), 16, msg=f"delivery cards: {delivery}")
        self.assertEqual(len(campaign_nodes()), 17,
                         msg="C-04 must carry 17 nodes: 16 delivery + 078 doc card")
        for name, text in (("NEXT-WINDOW.md", self.next_window),
                           ("README.md", self.readme),
                           ("control-tower/MAP.md", self.map_md)):
            self.assertIn("16-16", text, msg=f"{name} lost the 16-16 close-out")

    # -- 2. 078 is the 17th node, not a delivery card ----------------------
    def test_078_is_a_separate_doc_card(self) -> None:
        self.assertIn(DOC_CARD, campaign_nodes(),
                      msg="078 must be a C-04 roadmap node")
        self.assertNotIn(DOC_CARD, self.delivery_cards(),
                         msg="078 must not be counted as a delivery card")
        self.assertLessEqual(len(self.delivery_cards()), 16)
        for name, text in (("NEXT-WINDOW.md", self.next_window),
                           ("README.md", self.readme),
                           ("control-tower/MAP.md", self.map_md)):
            self.assertIn("17", text, msg=f"{name} must mention the 17-node campaign")
            self.assertIn("文档卡", text, msg=f"{name} must label 078 as a doc card")

    def test_16_16_is_not_16_verified_merges(self) -> None:
        self.assertIn("不是", self.next_window,
                      msg="NEXT-WINDOW must warn that 16-16 is not 16 verified merges")
        self.assertIn("MERGE_HISTORICAL", self.next_window,
                      msg="NEXT-WINDOW must record the 065-068 MERGE_HISTORICAL backfill")

    # -- 3. 072 void + parked spec ----------------------------------------
    def test_072_is_registered_void(self) -> None:
        entry = self.task_ids.get(VOID_CARD)
        self.assertIsNotNone(entry, msg="PILOT-072 must be registered in TASK_IDS")
        self.assertEqual(entry.get("status"), "void")
        self.assertEqual(entry.get("spec_path"), "pilot/PILOT-072.spec.json.parked")
        self.assertFalse(any(path.name == VOID_CARD for path in plain_task_dirs()),
                         msg="a void id must not have a live task directory")
        self.assertIn("072", self.next_window)
        self.assertIn("void", self.next_window)

    # -- 4. REPRODUCE and WALKTHROUGH -------------------------------------
    def test_reproduce_matches_the_ci_contract(self) -> None:
        self.assertIn(str(self.closeout_baseline()), self.reproduce)
        self.assertNotIn("252", self.reproduce,
                         msg="the stale 252-test expectation must be gone")
        self.assertIn("fetch-depth: 0", self.reproduce)
        self.assertIn("8 steps", self.reproduce)
        self.assertIn("docs/WALKTHROUGH.md", self.reproduce)
        self.assertIn("does not assert an online run", self.reproduce,
                      msg="REPRODUCE must not claim that online CI was verified")

    def test_walkthrough_covers_the_whole_path(self) -> None:
        for step in ("task-new", "dispatch", "deliver", "checkback", "envelope-new",
                     "queue-add", "merge-check", "post-merge"):
            self.assertIn(step, self.walkthrough, msg=f"walkthrough lost {step}")
        for judgement in ("owner", "reviewer", "16-16", "MERGE_HISTORICAL"):
            self.assertIn(judgement, self.walkthrough,
                          msg=f"walkthrough lost the {judgement} judgement")

    # -- 5. ARCHITECTURE numbers equal the arch-check inputs ---------------
    def test_architecture_numbers_match_the_arch_files(self) -> None:
        gates = len(load(TOWER / "arch" / "GATES.json")["gates"])
        events = len(load(TOWER / "EVENT_CATALOG.json")["events"])
        modules = len(list((TOWER / "tools").glob("tower_*.py")))
        self.assertIn(f"{gates} 道门", self.architecture)
        self.assertIn(f"{events} 条", self.architecture)
        self.assertIn(f"{modules} 个模块", self.architecture)


if __name__ == "__main__":
    unittest.main()
