"""Shape budget ratchet (PILOT-044)."""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
from tower_common import emit, fail, jload


SHAPE_BASELINE_SCHEMA = "tower/shape-baseline@1"


SHAPE_BASELINE_REL = "state/SHAPE-BASELINE.json"


SHAPE_MAX_FUNCTION_LINES = 80


SHAPE_MAX_FUNCTION_BRANCHES = 12


SHAPE_MAX_FILE_LINES = 600


SHAPE_DUP_WINDOW = 15


SHAPE_BRANCH_NODES = (ast.If, ast.For, ast.While, ast.Try,
                      ast.BoolOp, ast.IfExp, ast.ExceptHandler)


DELIVER_SHAPE_SKIPPED = "skipped"


def shape_py_files(root: Path) -> list[Path]:
    """Every scanned file: ``tools/*.py`` plus ``tools/tests/*.py``."""
    found: list[Path] = []
    for pattern in ("tools/*.py", "tools/tests/*.py"):
        for path in root.glob(pattern):
            if path.is_file() and "__pycache__" not in path.parts:
                found.append(path)
    return sorted(found)


def shape_branch_count(node: ast.AST) -> int:
    """Decision points under ``node``: the seven node kinds PILOT-044 counts."""
    return sum(1 for child in ast.walk(node) if isinstance(child, SHAPE_BRANCH_NODES))


def shape_function_stats(tree: ast.Module) -> dict[str, dict]:
    """Every function in the file: ``{"Class.method": {lines, branches}}``.

    Methods and nested functions are in scope: a 91-line class method or a long
    nested helper is exactly the debt the ratchet exists to catch.  Keys are
    qualified names so the baseline stays unambiguous.
    """
    stats: dict[str, dict] = {}
    shape_collect_functions(list(tree.body), "", stats)
    return stats


def shape_collect_functions(nodes: list[ast.AST], prefix: str,
                            stats: dict[str, dict]) -> None:
    """Record each def under ``nodes`` and recurse into its own scope."""
    for node in nodes:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            key = shape_unique_name(prefix + node.name, stats)
            stats[key] = {"lines": node.end_lineno - node.lineno + 1,
                          "branches": shape_branch_count(node)}
            shape_collect_functions(list(node.body), key + ".", stats)
        elif isinstance(node, ast.ClassDef):
            shape_collect_functions(list(node.body), prefix + node.name + ".", stats)
        else:
            shape_collect_functions(list(ast.iter_child_nodes(node)), prefix, stats)


def shape_unique_name(name: str, stats: dict[str, dict]) -> str:
    """A file-unique key, suffixing redefinitions (``m#1``)."""
    key = name
    suffix = 1
    while key in stats:
        key = f"{name}#{suffix}"
        suffix += 1
    return key


def shape_import_bindings(tree: ast.AST) -> list[tuple[str, int]]:
    """``(bound_name, lineno)`` for every import that binds a name."""
    bindings: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                bindings.append((alias.asname or alias.name.split(".")[0], node.lineno))
        elif isinstance(node, ast.ImportFrom):
            if node.module == "__future__":
                continue
            for alias in node.names:
                if alias.name == "*":
                    continue
                bindings.append((alias.asname or alias.name, node.lineno))
    return bindings


def shape_used_names(tree: ast.AST) -> set[str]:
    """Names referenced anywhere, plus the strings exported through ``__all__``."""
    used = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == "__all__":
                used |= {elt.value for elt in getattr(node.value, "elts", [])
                         if isinstance(elt, ast.Constant) and isinstance(elt.value, str)}
    return used


def shape_unused_imports(tree: ast.AST, text: str) -> list[str]:
    """Imported names the file never uses; a trailing ``# noqa`` opts out."""
    lines = text.splitlines()
    used = shape_used_names(tree)
    missing: set[str] = set()
    for name, lineno in shape_import_bindings(tree):
        if name in used or name in missing:
            continue
        line = lines[lineno - 1] if 0 < lineno <= len(lines) else ""
        if "# noqa" in line:
            continue
        missing.add(name)
    return sorted(missing)


def shape_duplicate_windows(text: str) -> list[str]:
    """SHA-256 of every ``SHAPE_DUP_WINDOW``-line window after normalisation.

    Normalisation drops indentation, blank lines and whole-line comments, so a
    copy/pasted block stays visible after re-indenting or re-commenting.
    """
    kept = [line.strip() for line in text.splitlines()]
    kept = [line for line in kept if line and not line.startswith("#")]
    digests: list[str] = []
    for start in range(len(kept) - SHAPE_DUP_WINDOW + 1):
        window = "\n".join(kept[start:start + SHAPE_DUP_WINDOW])
        digests.append(hashlib.sha256(window.encode("utf-8")).hexdigest())
    return digests


def shape_scan(root: Path) -> dict:
    """Scan one tower root into the ``tower/shape-baseline@1`` payload shape."""
    files: dict[str, dict] = {}
    unused: dict[str, list[str]] = {}
    counts: dict[str, int] = {}
    for path in shape_py_files(root):
        key = path.relative_to(root).as_posix()
        # ``utf-8-sig``: PILOT-042's test module starts with a BOM, which
        # ``ast.parse`` rejects but the interpreter tolerates.
        text = path.read_text(encoding="utf-8-sig")
        try:
            tree = ast.parse(text, filename=key)
        except SyntaxError as exc:
            fail([f"cannot parse {key}: {exc.msg}"])
        files[key] = {"lines": len(text.splitlines()),
                      "functions": shape_function_stats(tree)}
        missing = shape_unused_imports(tree, text)
        if missing:
            unused[key] = missing
        for digest in shape_duplicate_windows(text):
            counts[digest] = counts.get(digest, 0) + 1
    duplicates = sorted(digest for digest, count in counts.items() if count >= 2)
    return {"schema": SHAPE_BASELINE_SCHEMA, "files": files,
            "unused_imports": unused, "duplicate_blocks": duplicates}


def load_shape_baseline(path: Path) -> dict:
    """Load a baseline document, rejecting an unknown schema or file map."""
    try:
        data = jload(path)
    except (OSError, ValueError) as exc:
        fail([f"shape baseline unreadable: {SHAPE_BASELINE_REL} ({exc})"])
    if not isinstance(data, dict) or data.get("schema") != SHAPE_BASELINE_SCHEMA:
        fail([f"shape baseline schema must be {SHAPE_BASELINE_SCHEMA}"])
    if not isinstance(data.get("files"), dict):
        fail(["shape baseline files must be an object"])
    return data


def write_shape_baseline(path: Path, data: dict) -> None:
    """Write the baseline deterministically: sorted keys, LF endings, no timestamp."""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    # ``.gitattributes`` forces ``eol=lf`` for this artifact: writing LF here
    # keeps a regenerated baseline byte-identical to the committed one.
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def shape_file_errors(key: str, current: dict, frozen: dict | None) -> list[str]:
    """New/growing functions in one file, plus the new-file line budget."""
    errors: list[str] = []
    if frozen is None:
        if current["lines"] > SHAPE_MAX_FILE_LINES:
            errors.append(f"shape: new file {key} has {current['lines']} lines "
                          f"(> {SHAPE_MAX_FILE_LINES})")
        frozen_functions: dict = {}
    else:
        frozen_functions = frozen.get("functions") or {}
    for name, stats in sorted((current.get("functions") or {}).items()):
        base = frozen_functions.get(name)
        if base is None:
            if (stats["lines"] > SHAPE_MAX_FUNCTION_LINES
                    or stats["branches"] > SHAPE_MAX_FUNCTION_BRANCHES):
                errors.append(
                    f"shape: new function {name} in {key} has {stats['lines']} "
                    f"lines / {stats['branches']} branches (limits "
                    f"{SHAPE_MAX_FUNCTION_LINES}/{SHAPE_MAX_FUNCTION_BRANCHES})")
            continue
        if stats["lines"] > base.get("lines", 0):
            errors.append(f"shape: function {name} in {key} grew to "
                          f"{stats['lines']} lines (baseline {base.get('lines')})")
        if stats["branches"] > base.get("branches", 0):
            errors.append(f"shape: function {name} in {key} grew to "
                          f"{stats['branches']} branches (baseline {base.get('branches')})")
    return errors


def shape_duplicate_errors(current: dict, baseline: dict) -> list[str]:
    """Duplicated blocks the baseline did not already contain."""
    frozen = set(baseline.get("duplicate_blocks") or [])
    return [f"shape: new duplicated block (>={SHAPE_DUP_WINDOW} lines): {digest}"
            for digest in current.get("duplicate_blocks") or [] if digest not in frozen]


def shape_unused_import_errors(current: dict, baseline: dict) -> list[str]:
    """Unused imports the baseline did not already contain, per file."""
    frozen = baseline.get("unused_imports") or {}
    errors: list[str] = []
    for key, names in sorted((current.get("unused_imports") or {}).items()):
        allowed = set(frozen.get(key) or [])
        errors += [f"shape: unused import {name} in {key}" for name in names
                   if name not in allowed]
    return errors


def shape_debt_errors(current: dict, baseline: dict) -> list[str]:
    """Every new shape debt, or ``[]`` when the ratchet passes."""
    frozen_files = baseline.get("files") or {}
    errors: list[str] = []
    for key, entry in sorted((current.get("files") or {}).items()):
        errors += shape_file_errors(key, entry, frozen_files.get(key))
    errors += shape_duplicate_errors(current, baseline)
    errors += shape_unused_import_errors(current, baseline)
    return errors


def cmd_shape_check(root: Path, args) -> None:
    """Judge new shape debt against ``state/SHAPE-BASELINE.json``.

    ``--write-baseline`` rewrites the baseline and stops there (exit 0); it is
    never mixed with the gate, so a failing tower cannot be "fixed" by the same
    invocation that reports it.
    """
    baseline_path = root / SHAPE_BASELINE_REL
    if args.write_baseline:
        write_shape_baseline(baseline_path, shape_scan(root))
        emit({"ok": True, "shape_check": "baseline", "written": SHAPE_BASELINE_REL})
    if not baseline_path.is_file():
        fail([f"shape baseline missing: {SHAPE_BASELINE_REL}; "
              "run `towerctl shape-check --write-baseline` first"])
    current = shape_scan(root)
    errors = shape_debt_errors(current, load_shape_baseline(baseline_path))
    if errors:
        fail(errors, shape_check="failed", shape_checked=True)
    functions = sum(len(entry["functions"]) for entry in current["files"].values())
    emit({"ok": True, "shape_check": "checked", "shape_checked": True,
          "files": len(current["files"]), "functions": functions,
          "duplicate_blocks": len(current["duplicate_blocks"]),
          "unused_imports": sum(len(v) for v in current["unused_imports"].values())})
