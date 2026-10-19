"""Clause-to-test bindings for the tower specs and policies.

Keys are ``<front-matter spec id>/<clause id>``; values are existing test ids
in ``tools/tests/`` written as ``module.Class.test_method`` (the module is the
file name without ``.py``).

Every ``tool-check`` clause in the six tower documents is bound to at least one
test that actually exercises the clause's judgement method.  ``review-check``
and ``owner-gate`` clauses are intentionally absent: the coverage gate reports
them as manual / owner instead of failing.

``towerctl spec-coverage`` validates this file against the live specs and the
live tests, so a stale id (renamed test, removed clause) fails the gate.
"""

BINDINGS = {
    # -- WF-TASK -----------------------------------------------------------
    # INV-01: reviewer must be non-empty and must differ from the executor.
    "WF-TASK/INV-01": [
        "test_gates.TowerGateTestCase.test_checkback_rejects_whitespace_only_reviewer",
        "test_gates.TowerGateTestCase.test_checkback_rejects_reviewer_equal_to_executor",
    ],
    # INV-02: spec freezes at task creation; a changed spec_sha256 kills the gate.
    "WF-TASK/INV-02": [
        "test_gates.TowerGateTestCase.test_dispatch_rejects_spec_changed_after_task_new",
        "test_gates.TowerGateTestCase.test_check_ready_rejects_spec_changed_after_gate_pass",
    ],
    # INV-03: accept / close require non-empty evidence with matching SHA-256.
    "WF-TASK/INV-03": [
        "test_gates.TowerGateTestCase.test_accept_rejects_missing_evidence",
        "test_gates.TowerGateTestCase.test_accept_rejects_evidence_hash_mismatch",
        "test_gates.TowerGateTestCase.test_close_rejects_evidence_hash_mismatch",
    ],
    # INV-06: only the documented transitions may fire; no skipping straight
    # from ready to accepted/closed.
    "WF-TASK/INV-06": [
        "test_coverage.TaskInvariantTestCase.test_state_transitions_reject_skips",
    ],
    # INV-07: every state change leaves a ledger event.
    "WF-TASK/INV-07": [
        "test_coverage.TaskInvariantTestCase.test_every_state_change_writes_ledger_event",
    ],

    # -- WF-MERGE ----------------------------------------------------------
    # INV-01: envelope head B's parent must equal implementation head A.
    "WF-MERGE/INV-01": [
        "test_coverage.MergeInvariantTestCase.test_envelope_check_requires_parent_equal_implementation",
    ],
    # INV-02: A..B may only contain the envelope path.
    "WF-MERGE/INV-02": [
        "test_coverage.MergeInvariantTestCase.test_envelope_check_rejects_extra_files_in_envelope_commit",
    ],
    # INV-03: base must be an ancestor of A.
    "WF-MERGE/INV-03": [
        "test_coverage.MergeInvariantTestCase.test_envelope_check_requires_base_ancestor_of_implementation",
    ],
    # INV-04: merge runs only on the envelope base branch.
    "WF-MERGE/INV-04": [
        "test_gates.TowerGateTestCase.test_merge_rejects_current_branch_not_envelope_base",
    ],
    # INV-05: task accepted/closed + review PASS + reviewer != executor +
    # evidence hashes valid.
    "WF-MERGE/INV-05": [
        "test_coverage.MergeInvariantTestCase.test_envelope_check_requires_accepted_task_and_valid_evidence",
    ],
    # INV-06: only a WAITING / CORRECTION_REQUIRED entry may merge; an entry
    # already MERGING is rejected, so the queue stays serial.
    "WF-MERGE/INV-06": [
        "test_gates.TowerGateTestCase.test_merge_rejects_queue_entry_not_waiting",
    ],
    # INV-07: MERGED is not completion; only POST_MERGE_VERIFIED is.
    "WF-MERGE/INV-07": [
        "test_post_merge.PostMergeTestCase.test_unrelated_dirty_file_still_blocks",
        "test_post_merge.PostMergeTestCase.test_success_appends_ledger_event",
    ],

    # -- WF-LEDGER ---------------------------------------------------------
    # INV-01: seq starts at 1 and is continuous.
    "WF-LEDGER/INV-01": [
        "test_ledger_chain.LedgerChainTestCase.test_new_events_carry_valid_hash_chain",
        "test_ledger_chain.LedgerChainTestCase.test_deleted_row_breaks_seq_continuity",
    ],
    # INV-02: hash == sha256(canonical event without hash).
    "WF-LEDGER/INV-02": [
        "test_ledger_chain.LedgerChainTestCase.test_new_events_carry_valid_hash_chain",
        "test_ledger_chain.LedgerChainTestCase.test_tampered_hash_is_detected",
    ],
    # INV-03: prev_hash chains to the previous hash (or legacy raw row, or
    # GENESIS).
    "WF-LEDGER/INV-03": [
        "test_ledger_chain.LedgerChainTestCase.test_legacy_prefix_is_counted_and_chained",
        "test_ledger_chain.LedgerChainTestCase.test_tampered_prev_hash_is_detected",
    ],
    # INV-04: read max(seq)+append happens under the single-writer lock.
    "WF-LEDGER/INV-04": [
        "test_ledger_chain.LedgerChainTestCase.test_concurrent_appends_keep_sequence_and_chain",
        "test_ledger_lock_windows.LedgerLockWindowsTestCase.test_stress_20_rounds_of_concurrent_appends",
    ],
    # INV-05: legacy unhashed prefix is counted; an unhashed row after the
    # chain started is a failure.
    "WF-LEDGER/INV-05": [
        "test_ledger_chain.LedgerChainTestCase.test_legacy_prefix_is_counted_and_chained",
        "test_ledger_chain.LedgerChainTestCase.test_unhashed_row_after_chain_start_is_detected",
    ],

    # -- WF-HANDOFF --------------------------------------------------------
    # INV-01: receiver controller != source controller.
    "WF-HANDOFF/INV-01": [
        "test_coverage.HandoffInvariantTestCase.test_handoff_claim_rejects_source_controller",
    ],
    # INV-02: HANDOFF.md / SELF-CHECK.md hashes match the package record;
    # tampering with either file is detected (both assertions in one test).
    "WF-HANDOFF/INV-02": [
        "test_coverage.HandoffInvariantTestCase.test_handoff_check_detects_tampered_handoff_and_selfcheck",
    ],
    # INV-03: §0 anchors match the values captured at generation time; the
    # strengthened test drifts main SHA and queue status together.
    "WF-HANDOFF/INV-03": [
        "test_coverage.HandoffInvariantTestCase.test_handoff_check_detects_multiple_section0_drifts",
    ],
    # INV-04: claim -> receipt -> accept -> activate; no skipping.  Activate
    # before accept and receipt/accept before claim both fail.
    "WF-HANDOFF/INV-04": [
        "test_coverage.HandoffInvariantTestCase.test_handoff_activate_requires_acceptance",
        "test_coverage.HandoffInvariantTestCase.test_handoff_receipt_and_accept_before_claim_are_rejected",
    ],

    # -- POL-RED-LINES -----------------------------------------------------
    # C-09: fabricated evidence is caught by recomputing hashes and the chain.
    "POL-RED-LINES/C-09": [
        "test_gates.TowerGateTestCase.test_accept_rejects_evidence_hash_mismatch",
        "test_ledger_chain.LedgerChainTestCase.test_tampered_payload_is_detected",
    ],
    # C-11: self-review is rejected both at checkback and at merge.
    "POL-RED-LINES/C-11": [
        "test_gates.TowerGateTestCase.test_checkback_rejects_reviewer_equal_to_executor",
        "test_coverage.PolicyInvariantTestCase.test_merge_rejects_supervisor_equal_primary",
    ],
    # C-14: gate skipping is rejected (dispatch without spec gate, merge
    # without a queued entry) and MERGED alone never counts as completion --
    # only POST_MERGE_VERIFIED does.
    "POL-RED-LINES/C-14": [
        "test_gates.TowerGateTestCase.test_dispatch_rejects_missing_spec_gate",
        "test_gates.TowerGateTestCase.test_merge_rejects_queue_entry_not_waiting",
        "test_coverage.CompletionGateTestCase.test_merged_is_not_completion_until_post_merge_verified",
    ],

    # -- POL-CHANGE-LEVELS -------------------------------------------------
    # C-02: L1 changes need a task card, an independent reviewer (reviewer !=
    # executor at the envelope gate) and the merge / post-merge gates.
    "POL-CHANGE-LEVELS/C-02": [
        "test_coverage.MergeInvariantTestCase.test_merge_check_requires_independent_reviewer",
        "test_coverage.PolicyInvariantTestCase.test_envelope_new_requires_accepted_task_and_pass_review",
        "test_post_merge.PostMergeTestCase.test_rejects_envelope_that_was_never_merged",
    ],
    # C-03: L2 changes need the task card and a PASS review before accept/close.
    "POL-CHANGE-LEVELS/C-03": [
        "test_coverage.PolicyInvariantTestCase.test_accept_requires_pass_review",
        "test_gates.TowerGateTestCase.test_accept_then_close_happy_path",
    ],
    # C-08: an L1 change cannot bypass envelope + queue + merge gate.
    "POL-CHANGE-LEVELS/C-08": [
        "test_coverage.PolicyInvariantTestCase.test_merge_rejects_envelope_not_queued",
        "test_gates.TowerGateTestCase.test_merge_rejects_queue_entry_not_waiting",
    ],
}
