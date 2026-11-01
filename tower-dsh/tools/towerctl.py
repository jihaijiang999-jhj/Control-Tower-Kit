#!/usr/bin/env python3
"""Tower/DSH v0.3 pilot control-plane CLI (thin entry + compatibility facade).

The implementation lives in the ``tower_*`` modules (base -> domain ->
compose -> entry).  This file keeps the historical ``towerctl`` import
surface for the tests and runs ``tower_cli.main``.
"""
from __future__ import annotations

import os  # noqa: F401  (tests patch towerctl.os)
import sys
import types
from pathlib import Path  # noqa: F401

import tower_ledger
from tower_common import (  # noqa: F401
    COMMAND_ARCHIVE_SUFFIX, DEFAULT_ROOT, MergeBlocked, PACKAGE_ID_RE,
    PATH_ACCESS_ERRORS, SHA256_HEX_RE, TASK_BOARD_REL, TASK_ID_RE,
    TOOL_OWNED_STATE_DIRS, _contained_tower_path, _force_utf8_stdio,
    _is_executable_path, _lexical_tower_path, _looks_like_path, _norm_tower_rel,
    _optional_git, _optional_git_status, _path_has_symlink, _read_json_object,
    _split_argv, allowed_repo_path, check_package_id, check_task_id,
    command_failure, emit, emit_sorted, ensure_within, fail, gh_command, git,
    git_ok, is_safe_id, jdump, jload, now, rel, repo_relative,
    resolve_input_within, resolve_repository, sha256_file, status_path,
    tool_owned_paths, working_tree_state,
)
from tower_ledger import (  # noqa: F401
    AUTHORITY_LOCK_FILE, GENESIS_PREV_HASH, LEDGER_FILES,
    LEDGER_LOCK_POLL_INTERVAL, LEDGER_LOCK_STALE_AFTER, LEDGER_LOCK_TIMEOUT,
    LedgerLockTimeout, TASK_IDS_LOCK_FILE, TASK_IDS_REL, TASK_IDS_SCHEMA,
    TASK_ID_STATUSES, TASK_ID_VOID_RE, _acquire_lock_file, _append_ledger_event,
    _append_ledger_event_locked, _clear_stale_lock, _release_lock_file,
    activate_task_id, append_ledger, append_supervision_ledger, authority_lock,
    canonical_event_bytes, close_task_id, cmd_task_ids_init, cmd_task_ids_reserve,
    event_hash, ledger_lock, ledger_lock_path, ledger_rows, legacy_anchor,
    load_task_ids, parse_ledger_row, prev_hash_for_rows, scan_task_ids,
    spec_registry_errors, task_dir, task_id_base, task_id_dir_status,
    task_id_entry, task_id_record, task_id_spec_path, task_id_title, task_id_view,
    task_ids_lock, task_ids_save,
)
from tower_ledger_replay import (  # noqa: F401
    CHECKBACK_STATUSES, EMPTY_SUPERVISION_LEDGER, ENVELOPE_CORRECTION_EVENTS,
    ENVELOPE_LIFECYCLE_STATUS, ENVELOPE_MERGEABLE_STATUSES,
    ENVELOPE_MERGING_STATUS, ENVELOPE_REOPEN_STATUSES, ENVELOPE_TERMINAL_STATUSES,
    ENVELOPE_TRANSITIONS, TASK_LIFECYCLE_STATUS, TASK_TRANSITIONS,
    _fold_envelope_state, _illegal_transition, _sorted_states, cmd_verify_ledger,
    ledger_break_phrase, ledger_events_in_seq_order, ledger_events_naming,
    ledger_has_event, ledger_has_queue_add, ledger_payloads_by_task,
    ledger_precondition_breaks, replay_envelope_statuses, replay_task_statuses,
    supervision_artifacts, supervision_ledger_event_count, verify_ledger_file,
)
from tower_task import (  # noqa: F401
    ACCEPTANCE_DEFAULT_ITEM, ACCEPTANCE_ID_RE, ACCEPTANCE_JSON, ACCEPTANCE_KINDS,
    ACCEPTANCE_LEGACY_BEFORE, ACCEPTANCE_LEGACY_MAX, ACCEPTANCE_MD,
    ACCEPTANCE_SCHEMA, ACCEPTANCE_STATUSES, DEPENDS_ON_CLOSED, SPEC2_SCHEMA,
    SPEC_SCHEMA, SPEC_SCHEMAS, _latest_by, _load_optional_record,
    _optional_task_record, acceptance_json_path, acceptance_md_path,
    acceptance_row, canonical_task_dir, cmd_spec_approve, cmd_task_new,
    dependency_status_text, dependency_target_status, depends_on_structure_errors,
    ledger_has_task_event, load_board, load_record, read_task_records,
    render_acceptance_md, resolve_input, save_board, save_record, select_task,
    spec_gate_errors, task_new_card, task_new_errors, task_record_path,
    update_board, validate_spec, write_acceptance, write_default_acceptance,
    write_task_card,
)
from tower_command import (  # noqa: F401
    COMMAND_BRIEF_MAX_LINES, COMMAND_BUDGET_CARDS_RE, COMMAND_BUDGET_WEEKS_RE,
    COMMAND_CAMPAIGNS_REL, COMMAND_IN_FLIGHT, COMMAND_KEY_RE,
    COMMAND_REVIEW_WINDOW_DAYS, COMMAND_SCHEMAS, COMMAND_STRATEGY_REL,
    COMMAND_TERMINAL, CommandDocError, budget_card_limit, budget_week_limit,
    budget_window_warnings, campaign_relpaths, campaign_started,
    command_card_exists, command_date, command_doc_meta, command_finding,
    front_matter_block, load_command_doc, parse_command_front_matter, scalar_items,
    single_quoted_scalar, spec_only_warnings, task_force_ids, yaml_key_value,
    yaml_list_block, yaml_mapping_entry, yaml_mapping_item, yaml_scalar,
)
from tower_authority import (  # noqa: F401
    AUTHORITY_ABSENT, AUTHORITY_POLICY_FIELDS, AUTHORITY_POLICY_FILE,
    AUTHORITY_POLICY_SCHEMA, AUTHORITY_REQUIRED_EVENT, AUTHORITY_SET_EVENT,
    AUTHORITY_STATE_DIRS, AUTHORITY_STATE_FIELDS, AUTHORITY_STATE_FILE,
    AUTHORITY_STATE_SCHEMA, AUTHORITY_TEXT_FIELDS, _authority_field_errors,
    _authority_mismatch_detail, _authority_policy_payload,
    _authority_policy_value_ok, _authority_state_drift, _state_nested_id,
    _state_owner_name, authority_commit_hint, authority_display, authority_drift,
    authority_payload_fields, authority_policy_fields, authority_policy_invalid,
    authority_policy_mismatch, authority_policy_mismatch_detail,
    authority_policy_required, authority_repo, authority_required_event,
    authority_requirement, authority_requirement_errors, authority_state_fields,
    last_authority_event, last_authority_required_event, next_authority_revision,
)
from tower_authority_cmd import (  # noqa: F401
    authority_require_locked, authority_set_locked, authority_state_check,
    cmd_authority_check, cmd_authority_require, cmd_authority_set,
    ledger_empty_guard,
)
from tower_profile import (  # noqa: F401
    PROFILE_COLUMNS, PROFILE_EXPECT_RE, PROFILE_ID_RE, PROFILE_PROBES,
    PROFILE_PROBE_TIMEOUT, PROFILE_REL, PROFILE_SCHEMA, PROFILE_SEPARATOR_RE,
    PROFILE_STATUSES, ProfileDocError, _profile_base,
    _profile_worktree_matches_task, cmd_profile_check, load_profile, profile_cells,
    profile_document_findings, profile_execute, profile_expect, profile_finding,
    profile_front_matter, profile_load, profile_meta_findings, profile_meta_value,
    profile_row_findings, profile_run_probe, profile_select, profile_table_rows,
    resolve_pilot_paths,
)
from tower_shape import (  # noqa: F401
    DELIVER_SHAPE_SKIPPED, SHAPE_BASELINE_REL, SHAPE_BASELINE_SCHEMA,
    SHAPE_BRANCH_NODES, SHAPE_DUP_WINDOW, SHAPE_MAX_FILE_LINES,
    SHAPE_MAX_FUNCTION_BRANCHES, SHAPE_MAX_FUNCTION_LINES, cmd_shape_check,
    load_shape_baseline, shape_branch_count, shape_collect_functions,
    shape_debt_errors, shape_duplicate_errors, shape_duplicate_windows,
    shape_file_errors, shape_function_stats, shape_import_bindings, shape_py_files,
    shape_scan, shape_unique_name, shape_unused_import_errors,
    shape_unused_imports, shape_used_names, write_shape_baseline,
)
from tower_campaign import (  # noqa: F401
    POSITION_GLYPHS, POSITION_SCHEMA, POSITION_SOURCES, POSITION_STATUSES,
    PositionUnavailable, active_campaign, board_orphan_warnings, board_rows,
    board_shape_errors, campaign_check_report, campaign_coverage_ids,
    campaign_heading, campaign_map_progress, campaign_progress,
    campaign_roadmap_errors, campaign_wip_limit, check_strategy_doc,
    cmd_campaign_check, command_warnings, duplicate_id_errors, goal_link_errors,
    in_flight_ids, legacy_card_ids, load_campaign_docs, load_strategy_quiet,
    open_task_force_ids, position_context, position_fig_value, position_for,
    position_index, position_next, position_nodes, position_payload,
    position_review_lines, position_status, record_is_blocked, review_by_errors,
    review_warnings, roadmap_gap_warnings, roadmap_ids, roadmap_problem,
    strategy_goals, task_force_errors, wip_errors, with_position,
)
from tower_dispatch import (  # noqa: F401
    _dispatch_base_sha, _dispatch_base_sha_drift, _payload_base_sha, cmd_dispatch,
    deliver_dispatch_base_sha, dependency_closure_errors, dependency_cycle_errors,
    dispatch_base_sha, dispatch_campaign, dispatch_provenance_field,
    resolve_dispatch_worktree, scheduling_dependency_errors,
)
from tower_delivery import (  # noqa: F401
    COMPLETION_ADDED, COMPLETION_ENTRY_FIELDS, COMPLETION_TASK_STATUSES,
    DELIVER_SCOPE_SKIPPED, _completion_at_second, _completion_backing_entry_errors,
    _completion_entries_by_target, _completion_event_paths,
    _completion_field_differences, check_evidence, cmd_completion_add, cmd_deliver,
    collect_delivery_evidence, completion_backing_errors, completion_events,
    completion_paths, deliver_scope, deliver_shape_gate, delivery_gate_fields,
    shape_baseline_guard, write_delivery_md,
)
from tower_envelope import (  # noqa: F401
    REVIEW_CHECK, REVIEW_SCHEMA, STRUCTURE_PENDING, STRUCTURE_QUESTIONS,
    add_merge_ledger, checkback_reviewer, cmd_checkback, cmd_envelope_new,
    cmd_queue_add, envelope_checks, envelope_has_baselines, envelope_new_status,
    envelope_remerge_errors, load_queue, load_supervision, review_binding_check,
    review_json_path, review_mismatches, review_problems, save_queue,
    select_envelope, structure_review_lines, worktree_review_head,
    write_review_json, write_review_md,
)
from tower_handoff import (  # noqa: F401
    cmd_handoff_accept, cmd_handoff_activate, cmd_handoff_check, cmd_handoff_claim,
    cmd_handoff_new, cmd_handoff_receipt, cmd_handoff_status, current_snapshot,
    envelope_for_task, handoff_checks, match_task_by_evidence,
)
from tower_merge import (  # noqa: F401
    CHECKS_PENDING_EXIT, CHECKS_PENDING_RE, GH_AUTH_HINT, PR_URL_RE,
    block_pr_merge, checks_timeout_detail, cmd_merge, cmd_merge_check,
    expected_merge_head, merge_queue_errors, parse_created_pr, pr_fast_forward,
    pr_remote_merge, require_gh_auth, require_git, run_gh, wait_for_checks,
    write_task_merge_record,
)
from tower_arch import (  # noqa: F401
    ARCH_ADR_DIR, ARCH_ADR_SCHEMA, ARCH_ADR_STATUSES, ARCH_ADR_TEMPLATE,
    ARCH_DRIVE_RE, ARCH_EVENTS_REL, ARCH_EVENTS_SCHEMA, ARCH_FILE_REL,
    ARCH_GATES_REL, ARCH_GATES_SCHEMA, ARCH_GATE_IDS, ARCH_GRAPH_SCHEMA,
    ARCH_INVARIANTS_REL, ARCH_INVARIANTS_SCHEMA, ARCH_INVARIANT_IDS,
    ARCH_LEDGER_WRITERS, ARCH_SCHEMA, ARCH_SECTIONS, arch_constants,
    arch_event_types, arch_finding, arch_graph_nodes, arch_graph_payload,
    arch_graph_stem_findings, arch_imports, arch_literal, arch_load_json,
    arch_resolve_imports, arch_resolve_rel, arch_string_list, arch_test_names,
    arch_writer_ledger, cmd_arch_graph,
)
from tower_arch_check import (  # noqa: F401
    arch_adr_file_findings, arch_adr_findings, arch_adr_meta_findings,
    arch_architecture_findings, arch_boundary_findings, arch_check_payload,
    arch_command_names, arch_event_entry_findings, arch_event_fields_findings,
    arch_events_findings, arch_gate_field_findings, arch_gates_findings,
    arch_invariants_findings, arch_probe_findings, cmd_arch_check,
)
from tower_post_merge import (  # noqa: F401
    TEST_COUNT_RE, accept_card, acceptance_gate_errors, acceptance_item_errors,
    acceptance_legacy_ok, cmd_accept, cmd_acceptance_add, cmd_close, cmd_phase,
    cmd_post_merge, cmd_status, cmd_supervision_init, cmd_supervision_phase,
    cmd_supervision_status, cmd_task_next, load_acceptance,
    max_verified_tower_tests, parse_test_count, run_test_suite, valid_baseline,
    wiring_checks,
)
from tower_views import (  # noqa: F401
    cmd_init, cmd_startup, cmd_wiring,
)
from tower_lookup import (  # noqa: F401
    cmd_check, cmd_hash, cmd_where, position_delivery, position_human_lines,
    position_risk, position_spec_title,
)
from tower_status import (  # noqa: F401
    STATUS_ARCHIVE_REL, STATUS_CAMPAIGN_RE, STATUS_DIR_REL, STATUS_ENTRY_RE,
    STATUS_EVENTS, STATUS_INDEX_REL, STATUS_INDEX_SCHEMA, STATUS_WEEKLY_REL,
    brief_blocked_lines, brief_campaign_lines, brief_cap, brief_constraint_lines,
    brief_markdown, brief_next_lines, brief_pending_lines, brief_record_lines,
    brief_strategy_lines, brief_wip_lines, cmd_brief, cmd_status_archive,
    cmd_status_index, cmd_status_rollup, cmd_status_snapshot, read_current_state,
    status_append, status_archive, status_archive_line, status_base_figures,
    status_blocked_count, status_blocks, status_campaign_rollup,
    status_campaign_value, status_day_entries, status_day_file, status_dir_path,
    status_entry, status_entry_base_lines, status_entry_lines, status_figures,
    status_index_payload, status_moment, status_quarter, status_rollup_lines,
    status_snapshot_files, status_week_entries, status_wip_span, status_write_json,
    week_bounds,
)
from tower_state_verify import (  # noqa: F401
    _completion_drift, _completion_mismatch_drift, _evidence_entry_drift,
    _record_layer_drift, _skipped_completion_drift, _spec_drift, cmd_state_verify,
    state_verify_drift,
)
from tower_cli import (  # noqa: F401
    COMMAND_LAYER_HANDLERS, TASK_IDS_HANDLERS, acceptance_layer_parsers,
    arch_layer_parsers, build_parser, cli_commands, cmd_spec_coverage,
    cmd_spec_lint, command_layer_parsers, dispatch_campaign_parser, main,
    position_layer_parsers, profile_layer_parsers, review_layer_parsers,
    status_layer_parsers, task_ids_layer_parsers,
)

# The lock timings are still tuned through ``towerctl.LEDGER_LOCK_*`` by the
# ledger tests; forward those assignments to the module that reads them.
_LEDGER_TUNABLES = ("LEDGER_LOCK_TIMEOUT", "LEDGER_LOCK_STALE_AFTER",
                    "LEDGER_LOCK_POLL_INTERVAL")


class _FacadeModule(types.ModuleType):
    """Forward the three ledger lock tunables to ``tower_ledger``."""

    def __setattr__(self, name, value):
        if name in _LEDGER_TUNABLES:
            setattr(tower_ledger, name, value)
        super().__setattr__(name, value)


sys.modules[__name__].__class__ = _FacadeModule

if __name__ == "__main__":
    main()
