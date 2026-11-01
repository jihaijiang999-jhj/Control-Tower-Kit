"""arch-check findings and the reconciled payload."""
from __future__ import annotations

from pathlib import Path
from tower_common import emit
from tower_ledger import LEDGER_FILES
from tower_command import (
    CommandDocError, command_date, front_matter_block, parse_command_front_matter,
)
from tower_arch import (
    ARCH_ADR_DIR, ARCH_ADR_SCHEMA, ARCH_ADR_STATUSES, ARCH_ADR_TEMPLATE,
    ARCH_EVENTS_REL, ARCH_EVENTS_SCHEMA, ARCH_FILE_REL, ARCH_GATES_REL,
    ARCH_GATES_SCHEMA, ARCH_GATE_IDS, ARCH_INVARIANTS_REL, ARCH_INVARIANTS_SCHEMA,
    ARCH_INVARIANT_IDS, ARCH_SCHEMA, ARCH_SECTIONS, arch_event_types, arch_finding,
    arch_graph_payload, arch_load_json, arch_resolve_rel, arch_string_list,
    arch_test_names,
)


# Filled by ``tower_cli`` at import: the parser owns the command list.
CLI_COMMANDS: set[str] = set()


def arch_command_names() -> set[str]:
    """Every registered towerctl subcommand (the parser is the authority)."""
    return set(CLI_COMMANDS)


def arch_boundary_findings(graph: dict) -> list[dict]:
    """PILOT-048 boundary: ``tools/towerctl.py`` must never import the tests."""
    return [arch_finding("BOUNDARY_IMPORT", "tools/towerctl.py",
                         f"towerctl imports {edge['to']}")
            for edge in graph["edges"]
            if edge["from"] == "tools/towerctl.py"
            and edge["to"].startswith("tools/tests/")]


def arch_gate_field_findings(gate: dict, gid: str, commands: set[str],
                             tests: dict[str, str]) -> list[dict]:
    """One gate entry: command/phase/test/blocks presence and references."""
    findings: list[dict] = []
    command = gate.get("command")
    if command not in commands:
        findings.append(arch_finding(
            "GATE_COMMAND", gid,
            f"command {command!r} is not a towerctl subcommand"))
    test = gate.get("test")
    if not (isinstance(test, str) and test in tests):
        findings.append(arch_finding(
            "GATE_TEST", gid, f"test {test!r} is not in tools/tests/*.py"))
    for field in ("phase", "blocks"):
        value = gate.get(field)
        if not (isinstance(value, str) and value.strip()):
            findings.append(arch_finding(
                "GATE_FIELD", gid, f"{field} must be a non-empty string"))
    return findings


def arch_gates_findings(root: Path, commands: set[str], tests: dict[str, str]):
    """``arch/GATES.json``: references, duplicates and required gate ids."""
    data, findings = arch_load_json(root, ARCH_GATES_REL, ARCH_GATES_SCHEMA)
    if data is None:
        return findings, 0
    gates = data.get("gates")
    if not isinstance(gates, list):
        return findings + [arch_finding("GATES_SHAPE", ARCH_GATES_REL,
                                        "gates must be a list")], 0
    seen: set[str] = set()
    for index, gate in enumerate(gates):
        target = f"{ARCH_GATES_REL}#gates[{index}]"
        if not isinstance(gate, dict):
            findings.append(arch_finding("GATE_SHAPE", target,
                                         "gate must be an object"))
            continue
        gid = gate.get("id")
        if not (isinstance(gid, str) and gid):
            findings.append(arch_finding("GATE_SHAPE", target,
                                         "id must be a non-empty string"))
            continue
        if gid in seen:
            findings.append(arch_finding("GATE_DUPLICATE", gid,
                                         "id appears twice"))
            continue
        seen.add(gid)
        findings += arch_gate_field_findings(gate, gid, commands, tests)
    findings += [arch_finding("GATE_MISSING", gid, "required gate is missing")
                 for gid in ARCH_GATE_IDS if gid not in seen]
    return findings, len(gates)


def arch_probe_findings(probe, target: str, commands: set[str],
                        tests: dict[str, str]) -> list[dict]:
    """One invariant probe: ``kind`` test|command and an existing ``ref``."""
    if not isinstance(probe, dict):
        return [arch_finding("INVARIANT_PROBE", target,
                             "probe must be an object")]
    kind = probe.get("kind")
    pools = {"test": tests, "command": commands}
    pool = pools.get(kind)
    if pool is None:
        return [arch_finding("INVARIANT_PROBE", target,
                             f"kind {kind!r} must be test or command")]
    ref = probe.get("ref")
    if not (isinstance(ref, str) and ref in pool):
        return [arch_finding("INVARIANT_PROBE", target,
                             f"{kind} ref {ref!r} does not exist")]
    return []


def arch_invariants_findings(root: Path, commands: set[str],
                             tests: dict[str, str]):
    """``arch/INVARIANTS.json``: C-01..C-16, each with an existing probe."""
    data, findings = arch_load_json(root, ARCH_INVARIANTS_REL,
                                    ARCH_INVARIANTS_SCHEMA)
    if data is None:
        return findings, 0
    invariants = data.get("invariants")
    if not isinstance(invariants, list):
        return findings + [arch_finding("INVARIANTS_SHAPE", ARCH_INVARIANTS_REL,
                                        "invariants must be a list")], 0
    seen: set[str] = set()
    for index, item in enumerate(invariants):
        target = f"{ARCH_INVARIANTS_REL}#invariants[{index}]"
        if not isinstance(item, dict):
            findings.append(arch_finding("INVARIANT_SHAPE", target,
                                         "entry must be an object"))
            continue
        invariant_id = item.get("id")
        if not (isinstance(invariant_id, str) and invariant_id):
            findings.append(arch_finding("INVARIANT_SHAPE", target,
                                         "id must be a non-empty string"))
            continue
        if invariant_id in seen:
            findings.append(arch_finding("INVARIANT_DUPLICATE", invariant_id,
                                         "id appears twice"))
            continue
        seen.add(invariant_id)
        if not (isinstance(item.get("text"), str) and item["text"].strip()):
            findings.append(arch_finding("INVARIANT_TEXT", invariant_id,
                                         "text must be a non-empty string"))
        findings += arch_probe_findings(item.get("probe"), invariant_id,
                                        commands, tests)
    findings += [arch_finding("INVARIANT_MISSING", invariant_id,
                              "required clause is missing")
                 for invariant_id in ARCH_INVARIANT_IDS
                 if invariant_id not in seen]
    return findings, len(invariants)


def arch_event_fields_findings(entry: dict, event: str,
                               commands: set[str]) -> list[dict]:
    """One catalog entry: producer, payload keys, state flag, drifts and note."""
    findings: list[dict] = []
    if entry.get("producer") not in commands:
        findings.append(arch_finding(
            "EVENT_PRODUCER", event,
            f"producer {entry.get('producer')!r} is not a towerctl subcommand"))
    if not arch_string_list(entry.get("payload_required")):
        findings.append(arch_finding(
            "EVENT_PAYLOAD", event,
            "payload_required must be a list of non-empty strings"))
    if not isinstance(entry.get("state_verify"), bool):
        findings.append(arch_finding("EVENT_FIELD", event,
                                     "state_verify must be a boolean"))
    if not arch_string_list(entry.get("drift_kinds")):
        findings.append(arch_finding("EVENT_FIELD", event,
                                     "drift_kinds must be a list of strings"))
    if not (isinstance(entry.get("note"), str) and entry["note"].strip()):
        findings.append(arch_finding("EVENT_FIELD", event,
                                     "note must be a non-empty string"))
    return findings


def arch_event_entry_findings(entry, index: int, commands: set[str],
                              code_types: dict[str, str]) -> list[dict]:
    """One EVENT_CATALOG entry: shape, ledger and code linkage."""
    target = f"{ARCH_EVENTS_REL}#events[{index}]"
    if not isinstance(entry, dict):
        return [arch_finding("EVENT_SHAPE", target, "entry must be an object")]
    event = entry.get("type")
    if not (isinstance(event, str) and event):
        return [arch_finding("EVENT_SHAPE", target,
                             "type must be a non-empty string")]
    findings: list[dict] = []
    ledger = entry.get("ledger")
    if ledger not in LEDGER_FILES:
        findings.append(arch_finding("EVENT_LEDGER", event,
                                     "ledger must be primary or supervision"))
    if event not in code_types:
        findings.append(arch_finding("EVENT_EXTRA", event,
                                     "type does not appear in towerctl.py"))
    elif ledger != code_types[event]:
        findings.append(arch_finding(
            "EVENT_LEDGER", event,
            f"catalog says {ledger}, code appends to {code_types[event]}"))
    findings += arch_event_fields_findings(entry, event, commands)
    return findings


def arch_events_findings(root: Path, commands: set[str],
                         code_types: dict[str, str]):
    """``EVENT_CATALOG.json`` against the call sites: bidirectional equality."""
    data, findings = arch_load_json(root, ARCH_EVENTS_REL, ARCH_EVENTS_SCHEMA)
    if data is None:
        return findings, 0
    entries = data.get("events")
    if not isinstance(entries, list):
        return findings + [arch_finding("EVENTS_SHAPE", ARCH_EVENTS_REL,
                                        "events must be a list")], 0
    seen: dict[str, int] = {}
    for index, entry in enumerate(entries):
        findings += arch_event_entry_findings(entry, index, commands, code_types)
        if isinstance(entry, dict) and isinstance(entry.get("type"), str):
            seen[entry["type"]] = seen.get(entry["type"], 0) + 1
    findings += [arch_finding("EVENT_DUPLICATE", event, "type appears twice")
                 for event, count in sorted(seen.items()) if count > 1]
    findings += [arch_finding("EVENT_MISSING", event,
                              "code appends this type but the catalog omits it")
                 for event in sorted(set(code_types) - set(seen))]
    return findings, len(entries)


def arch_adr_meta_findings(root: Path, meta: dict, relpath: str) -> list[dict]:
    """ADR front-matter schema, id, status, date, cards and existing files."""
    findings: list[dict] = []
    if meta.get("schema") != ARCH_ADR_SCHEMA:
        findings.append(arch_finding("ADR_SCHEMA", relpath,
                                     f"schema must be {ARCH_ADR_SCHEMA}"))
    if not (isinstance(meta.get("id"), str) and meta["id"].strip()):
        findings.append(arch_finding("ADR_FIELD", relpath,
                                     "id must be a non-empty string"))
    if meta.get("status") not in ARCH_ADR_STATUSES:
        findings.append(arch_finding(
            "ADR_STATUS", relpath,
            f"status {meta.get('status')!r} is not one of {ARCH_ADR_STATUSES}"))
    if command_date(meta.get("date")) is None:
        findings.append(arch_finding("ADR_FIELD", relpath,
                                     "date must be YYYY-MM-DD"))
    if not isinstance(meta.get("related_cards"), list):
        findings.append(arch_finding("ADR_FIELD", relpath,
                                     "related_cards must be a list"))
    related = meta.get("related_files")
    if not arch_string_list(related):
        findings.append(arch_finding("ADR_FIELD", relpath,
                                     "related_files must be a non-empty list"))
        return findings
    findings += [arch_finding("ADR_RELATED", relpath,
                              f"related file does not exist: {item}")
                 for item in related if arch_resolve_rel(root, item) is None]
    return findings


def arch_adr_file_findings(root: Path, path: Path) -> list[dict]:
    """Read one ADR and check its front-matter; a missing fence is one error."""
    relpath = f"{ARCH_ADR_DIR}/{path.name}"
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError) as exc:
        return [arch_finding("ADR_UNREADABLE", relpath, str(exc))]
    try:
        meta = parse_command_front_matter(front_matter_block(text))
    except CommandDocError as exc:
        return [arch_finding("ADR_FRONT_MATTER", relpath, str(exc))]
    return arch_adr_meta_findings(root, meta, relpath)


def arch_adr_findings(root: Path):
    """Every ``adr/*.md`` except the template: front-matter and related files."""
    adr_dir = root / ARCH_ADR_DIR
    if not adr_dir.is_dir():
        return [arch_finding("ADR_MISSING", ARCH_ADR_DIR,
                             "adr/ directory is missing")], 0
    findings: list[dict] = []
    count = 0
    for path in sorted(adr_dir.glob("*.md")):
        if path.name == ARCH_ADR_TEMPLATE:
            continue
        count += 1
        findings += arch_adr_file_findings(root, path)
    if not count:
        findings.append(arch_finding("ADR_MISSING", ARCH_ADR_DIR,
                                     "no ADR document"))
    return findings, count


def arch_architecture_findings(root: Path):
    """``ARCHITECTURE.md``: front-matter fields plus the six fixed sections."""
    path = root / ARCH_FILE_REL
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError) as exc:
        return [arch_finding("ARCH_MISSING", ARCH_FILE_REL, str(exc))], 0
    try:
        meta = parse_command_front_matter(front_matter_block(text))
    except CommandDocError as exc:
        return [arch_finding("ARCH_FRONT_MATTER", ARCH_FILE_REL, str(exc))], 0
    findings: list[dict] = []
    if meta.get("schema") != ARCH_SCHEMA:
        findings.append(arch_finding("ARCH_SCHEMA", ARCH_FILE_REL,
                                     f"schema must be {ARCH_SCHEMA}"))
    for field in ("id", "version", "updated", "review_by", "owner"):
        if not (isinstance(meta.get(field), str) and meta[field].strip()):
            findings.append(arch_finding(
                "ARCH_FIELD", ARCH_FILE_REL,
                f"{field} must be a non-empty string"))
    headings = {line.strip() for line in text.splitlines()}
    findings += [arch_finding("ARCH_SECTION", ARCH_FILE_REL,
                              f"missing section {title}")
                 for title in ARCH_SECTIONS if title not in headings]
    return findings, len(ARCH_SECTIONS)


def arch_check_payload(root: Path) -> dict:
    """The full ``arch-check`` result: counts plus every finding (read-only)."""
    commands = arch_command_names()
    tests, findings = arch_test_names(root)
    code_types, scan_findings, unresolved = arch_event_types(root)
    findings += scan_findings
    gates, gate_count = arch_gates_findings(root, commands, tests)
    invariants, invariant_count = arch_invariants_findings(root, commands, tests)
    events, event_count = arch_events_findings(root, commands, code_types)
    adrs, adr_count = arch_adr_findings(root)
    sections, section_count = arch_architecture_findings(root)
    graph, graph_findings = arch_graph_payload(root)
    findings += gates + invariants + events + adrs + sections + graph_findings
    findings += arch_boundary_findings(graph)
    findings.sort(key=lambda item: (item["code"], item["target"], item["detail"]))
    counts = {"gates": gate_count, "invariants": invariant_count,
              "events": event_count, "event_types_in_code": len(code_types),
              "unresolved_event_calls": unresolved, "adrs": adr_count,
              "sections": section_count, "nodes": len(graph["nodes"]),
              "edges": len(graph["edges"])}
    return {"ok": not findings, "counts": counts, "errors": findings}


def cmd_arch_check(root: Path, args) -> None:
    """Read-only: reconcile ARCHITECTURE/GATES/INVARIANTS/EVENT_CATALOG with code."""
    payload = arch_check_payload(root)
    if not payload["ok"]:
        emit({"ok": False, "errors": payload["errors"]}, 2)
    emit({"ok": True, "counts": payload["counts"], "errors": []}, 0)
