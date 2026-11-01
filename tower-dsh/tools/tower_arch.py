"""Architecture spine: gates/invariants/events graph primitives."""
from __future__ import annotations

import ast
import re
from pathlib import Path
from tower_common import emit, emit_sorted, jload
from tower_ledger import LEDGER_FILES


ARCH_SCHEMA = "tower/architecture@1"


ARCH_FILE_REL = "ARCHITECTURE.md"


ARCH_GATES_REL = "arch/GATES.json"


ARCH_INVARIANTS_REL = "arch/INVARIANTS.json"


ARCH_EVENTS_REL = "EVENT_CATALOG.json"


ARCH_ADR_DIR = "adr"


ARCH_ADR_TEMPLATE = "ADR-TEMPLATE.md"


ARCH_GATES_SCHEMA = "tower/gates@1"


ARCH_INVARIANTS_SCHEMA = "tower/invariants@1"


ARCH_EVENTS_SCHEMA = "tower/event-catalog@1"


ARCH_ADR_SCHEMA = "tower/adr@1"


ARCH_GRAPH_SCHEMA = "tower/arch-graph@1"


ARCH_ADR_STATUSES = ("proposed", "accepted", "superseded", "archived")


ARCH_DRIVE_RE = re.compile(r"^[A-Za-z]:")


ARCH_SECTIONS = (
    "## 1. 系统上下文", "## 2. 组件与职责", "## 3. 数据流",
    "## 4. 关键契约", "## 5. 扩展点", "## 6. 不变量")


ARCH_GATE_IDS = (
    "GATE-SPEC", "GATE-SPEC-OBJECTIVE", "GATE-READY", "GATE-DISPATCH",
    "GATE-DELIVER-SCOPE",
    "GATE-DELIVER-BASE-SHA", "GATE-DELIVER-SHAPE", "GATE-REVIEW",
    "GATE-ACCEPT", "GATE-CLOSE", "GATE-ENVELOPE", "GATE-QUEUE",
    "GATE-MERGE-CHECK", "GATE-MERGE-PREFLIGHT", "GATE-POST-MERGE", "GATE-CI",
    "GATE-PROFILE", "GATE-MODULES")


ARCH_INVARIANT_IDS = tuple(f"C-{index:02d}" for index in range(1, 17))


ARCH_LEDGER_WRITERS = {
    "append_ledger": (1, "primary"),
    "append_supervision_ledger": (1, "supervision"),
    "_append_ledger_event_locked": (2, None)}


def arch_finding(code: str, target: str, detail: str) -> dict:
    """One ``arch-check`` error: ``{code, target, detail}`` (sorted on emit)."""
    return {"code": code, "target": target, "detail": detail}


def arch_string_list(value) -> bool:
    """True for a list of non-empty strings (payload_required, drift kinds)."""
    return isinstance(value, list) and all(
        isinstance(item, str) and item.strip() for item in value)


def arch_load_json(root: Path, relpath: str, schema: str):
    """Read one machine document; ``(data | None, findings)``, never raises."""
    try:
        data = jload(root / relpath)
    except (OSError, ValueError) as exc:
        return None, [arch_finding("JSON_UNREADABLE", relpath, str(exc))]
    if not isinstance(data, dict):
        return None, [arch_finding("JSON_SHAPE", relpath,
                                   "top level must be an object")]
    if data.get("schema") != schema:
        return None, [arch_finding("JSON_SCHEMA", relpath,
                                   f"schema must be {schema}")]
    return data, []


def arch_test_names(root: Path):
    """``({test function name: file}, findings)`` over ``tools/tests/*.py``."""
    names: dict[str, str] = {}
    findings: list[dict] = []
    for path in sorted((root / "tools" / "tests").glob("*.py")):
        relpath = f"tools/tests/{path.name}"
        try:
            tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=relpath)
        except (OSError, SyntaxError, UnicodeError) as exc:
            findings.append(arch_finding("TESTS_UNREADABLE", relpath, str(exc)))
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name.startswith("test"):
                names.setdefault(node.name, relpath)
    if not names:
        findings.append(arch_finding("TESTS_MISSING", "tools/tests",
                                     "no test functions found"))
    return names, findings


def arch_constants(tree: ast.Module) -> dict[str, str]:
    """Module-level ``NAME = "literal"`` assignments (event type constants)."""
    found: dict[str, str] = {}
    for node in tree.body:
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)):
            found[node.targets[0].id] = node.value.value
    return found


def arch_literal(node, consts: dict[str, str]) -> str | None:
    """The string value of a literal or of a module-level string constant."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return consts.get(node.id)
    return None


def arch_writer_ledger(node: ast.Call, consts: dict[str, str],
                       writer: str) -> str | None:
    """Which ledger a writer call appends to, or None when it cannot be read."""
    fixed = ARCH_LEDGER_WRITERS[writer][1]
    if fixed is not None:
        return fixed
    if len(node.args) < 2:
        return None
    subscript = node.args[1]
    if not (isinstance(subscript, ast.Subscript)
            and isinstance(subscript.value, ast.Name)
            and subscript.value.id == "LEDGER_FILES"):
        return None
    key = arch_literal(subscript.slice, consts)
    return key if key in LEDGER_FILES else None


def arch_event_types(root: Path):
    """``({type: ledger}, findings, unresolved)`` from ledger writer call sites.

    Only literal strings and module-level string constants are collected, as
    the card requires.  PILOT-056 moved the implementation into the top-level
    ``tools/tower_*.py`` modules, so every such module is scanned; their string
    constants share one namespace (a writer may import the constant from the
    module that defines it).  The internal forwarder ``_append_ledger_event``
    passes its ``event_type`` parameter through to
    ``_append_ledger_event_locked``, so that call is counted as unresolved
    instead of guessed.
    """
    paths = sorted(path for path in (root / "tools").glob("*.py")
                   if path.is_file())
    trees: list[tuple[str, ast.Module, dict[str, str]]] = []
    findings: list[dict] = []
    global_consts: dict[str, str] = {}
    for path in paths:
        relpath = f"tools/{path.name}"
        try:
            tree = ast.parse(path.read_text(encoding="utf-8-sig"),
                             filename=relpath)
        except (OSError, SyntaxError, UnicodeError) as exc:
            findings.append(arch_finding("TOWERCTL_UNREADABLE", relpath, str(exc)))
            continue
        consts = arch_constants(tree)
        global_consts.update(consts)
        trees.append((relpath, tree, consts))
    found: dict[str, str] = {}
    unresolved = 0
    for _relpath, tree, consts in trees:
        merged = {**global_consts, **consts}
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)):
                continue
            writer = node.func.id
            if writer not in ARCH_LEDGER_WRITERS:
                continue
            index = ARCH_LEDGER_WRITERS[writer][0]
            argument = node.args[index] if len(node.args) > index else None
            event = arch_literal(argument, merged)
            ledger = arch_writer_ledger(node, merged, writer)
            if event is None or ledger is None:
                unresolved += 1
                continue
            if found.setdefault(event, ledger) != ledger:
                findings.append(arch_finding(
                    "EVENT_LEDGER", event,
                    f"appended to both {found[event]} and {ledger}"))
    return found, findings, unresolved


def arch_graph_nodes(root: Path) -> list[str]:
    """Every ``tools/**/*.py`` module path, sorted (the graph's node set)."""
    nodes = [path.relative_to(root).as_posix()
             for path in root.glob("tools/**/*.py")
             if path.is_file() and "__pycache__" not in path.parts]
    return sorted(set(nodes))


def arch_imports(tree: ast.Module) -> set[str]:
    """Every imported module/name (``import x.y`` and ``from a.b import c``)."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                names.add(node.module)
            names.update(alias.name for alias in node.names)
    return names


def arch_resolve_imports(names: set[str], by_module: dict[str, str]) -> set[str]:
    """Map imported names to local node paths by their last dotted component."""
    resolved: set[str] = set()
    for name in names:
        target = by_module.get(name.split(".")[-1])
        if target:
            resolved.add(target)
    return resolved


def arch_graph_stem_findings(nodes: list[str]) -> list[dict]:
    """Two tools modules with the same stem make import edges ambiguous."""
    counts: dict[str, int] = {}
    for node in nodes:
        stem = Path(node).stem
        counts[stem] = counts.get(stem, 0) + 1
    return [arch_finding("GRAPH_STEM_DUPLICATE", stem,
                         "two tools modules share this stem; import edges are "
                         "ambiguous")
            for stem, count in sorted(counts.items()) if count > 1]


def arch_graph_payload(root: Path):
    """``(payload, findings)`` for ``tower/arch-graph@1``; keys sorted on emit."""
    nodes = arch_graph_nodes(root)
    by_module: dict[str, str] = {}
    for node in nodes:
        by_module.setdefault(Path(node).stem, node)
    edges: list[dict] = []
    findings = arch_graph_stem_findings(nodes)
    for node in nodes:
        try:
            tree = ast.parse((root / node).read_text(encoding="utf-8-sig"),
                             filename=node)
        except (OSError, SyntaxError, UnicodeError) as exc:
            findings.append(arch_finding("GRAPH_UNREADABLE", node, str(exc)))
            continue
        for target in sorted(arch_resolve_imports(arch_imports(tree), by_module)):
            if target != node:
                edges.append({"from": node, "to": target})
    edges.sort(key=lambda edge: (edge["from"], edge["to"]))
    payload = {"schema": ARCH_GRAPH_SCHEMA, "nodes": nodes, "edges": edges}
    return payload, findings


def arch_resolve_rel(root: Path, raw) -> Path | None:
    """Resolve one tower/repo-relative reference inside the tower root, or None.

    Fail closed: absolute paths, Windows drive paths (``C:/...``), ``..``
    segments and anything whose resolved target leaves the tower root (symlink
    escapes included) are rejected, so an ADR cannot vouch for a host file.
    """
    text = str(raw or "").replace("\\", "/").strip()
    if (not text or text.startswith("/") or ARCH_DRIVE_RE.match(text)
            or ".." in text.split("/")):
        return None
    root_abs = root.resolve()
    candidates = [root / text, root.parent / text]
    if text.startswith(root.name + "/"):
        candidates.append(root / text[len(root.name) + 1:])
    for candidate in candidates:
        if not candidate.is_file():
            continue
        resolved = candidate.resolve()
        if resolved == root_abs or root_abs in resolved.parents:
            return resolved
    return None


def cmd_arch_graph(root: Path, args) -> None:
    """Read-only: print the deterministic ``tower/arch-graph@1`` import graph."""
    graph, findings = arch_graph_payload(root)
    if findings:
        emit({"ok": False, "errors": findings}, 2)
    emit_sorted(graph)
