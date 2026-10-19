"""Clause-to-test coverage gate for tower workflow specs and policies.

The gate connects three sources:

* the six tower documents (``specs/WF-*.md`` plus root-level
  ``tower/policy@1`` files) -- parsed with the same front-matter / pipe-table
  helpers as :mod:`spec_lint`, so there is no second Markdown dialect;
* ``tools/tests/clause_bindings.py`` -- the hand-maintained ``BINDINGS`` map
  from ``<spec-id>/<clause-id>`` to test ids;
* ``tools/tests/test_*.py`` -- scanned statically with :mod:`ast` for every
  ``def test_*`` inside a ``class``, producing ``module.Class.method`` ids.

A ``tool-check`` clause with no binding is a ``tool_gap``; a binding whose
clause or test id does not exist is ``unknown``.  ``review-check`` and
``owner-gate`` clauses are reported as ``manual`` / ``owner`` and never fail
the gate.  Everything is local, stdlib-only and read-only.
"""
from __future__ import annotations

import argparse
import ast
import importlib.util
import json
import sys
from pathlib import Path

import spec_lint

TOOL = "tool-check"
REVIEW = "review-check"
OWNER = "owner-gate"
KNOWN_ENFORCEMENTS = frozenset({TOOL, REVIEW, OWNER})
DEFAULT_BINDINGS = Path("tools") / "tests" / "clause_bindings.py"
DEFAULT_TESTS_DIR = Path("tools") / "tests"
BINDINGS_VAR = "BINDINGS"


def _resolve(root: Path, value, default: Path) -> Path:
    """Resolve a CLI override against the tower root, or use the default."""
    if value is None:
        return root / default
    path = Path(value)
    return path if path.is_absolute() else root / path


def _display(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.name


def _front_matter(path: Path) -> dict[str, str]:
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return {}
    fields, _body_start, _errors = spec_lint.parse_front_matter(text.splitlines())
    return fields


def spec_files(root: Path) -> list[Path]:
    """The same document set ``spec_lint.lint_root`` checks.

    Every ``specs/*.md`` is included (workflow or policy), plus root-level
    Markdown whose front matter declares ``tower/policy@1``.
    """
    files: list[Path] = []
    specs = root / "specs"
    if specs.is_dir():
        files.extend(sorted(specs.glob("*.md")))
    for path in sorted(root.glob("*.md")):
        if path in files:
            continue
        if _front_matter(path).get("schema") == spec_lint.POLICY_SCHEMA:
            files.append(path)
    return files


def _clause_section(fields: dict[str, str]) -> int:
    if fields.get("schema") == spec_lint.POLICY_SCHEMA:
        return 2  # policy: ## 2. 条款
    return 4  # workflow: ## 4. 不变量


def collect_clauses(root: Path) -> tuple[list[dict], set[str], list[str]]:
    """Return ``(clauses, spec_ids, errors)`` for every parsed document."""
    clauses: list[dict] = []
    spec_ids: set[str] = set()
    errors: list[str] = []
    seen: set[str] = set()
    for path in spec_files(root):
        display = _display(root, path)
        fields = _front_matter(path)
        spec_id = (fields.get("id") or "").strip()
        if not spec_id:
            errors.append(f"{display}: missing front matter id")
            continue
        spec_ids.add(spec_id)
        try:
            text = path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeDecodeError) as exc:
            errors.append(f"{display}: cannot read file: {exc}")
            continue
        lines = text.splitlines()
        _fields, body_start, _front_errors = spec_lint.parse_front_matter(lines)
        sections = spec_lint.parse_sections(lines[body_start:])
        section_no = _clause_section(fields)
        tables = spec_lint.parse_tables(sections.get(section_no, []))
        if not tables:
            errors.append(f"{display}: no clause table in section {section_no}")
            continue
        header, rows = tables[0]
        enforcement_col = None
        for index, name in enumerate(header):
            if spec_lint.unbacktick(name) == "enforcement":
                enforcement_col = index
                break
        if enforcement_col is None:
            errors.append(f"{display}: clause table has no enforcement column")
            continue
        for row_no, row in enumerate(rows, 1):
            if not row:
                continue
            clause_id = spec_lint.unbacktick(row[0])
            if not clause_id:
                errors.append(f"{display}: data row {row_no} has no clause id")
                continue
            key = f"{spec_id}/{clause_id}"
            if key in seen:
                errors.append(f"{display}: duplicate clause {key}")
                continue
            seen.add(key)
            enforcement = ""
            if len(row) > enforcement_col:
                enforcement = spec_lint.unbacktick(row[enforcement_col])
            clauses.append({"spec": spec_id, "id": clause_id,
                            "enforcement": enforcement})
    return clauses, spec_ids, errors


def collect_test_ids(tests_dir: Path) -> tuple[set[str], list[str]]:
    """Statically read ``module.Class.test_method`` ids from ``test_*.py``."""
    test_ids: set[str] = set()
    errors: list[str] = []
    if not tests_dir.is_dir():
        return test_ids, [f"tests directory not found: {tests_dir}"]
    for path in sorted(tests_dir.glob("test_*.py")):
        module = path.stem
        try:
            tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        except (OSError, UnicodeDecodeError, SyntaxError) as exc:
            errors.append(f"{path.name}: cannot parse tests: {exc}")
            continue
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            for item in node.body:
                if (isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
                        and item.name.startswith("test_")):
                    test_ids.add(f"{module}.{node.name}.{item.name}")
    return test_ids, errors


def load_bindings(path: Path) -> tuple[dict, list[str]]:
    """Execute the bindings module and return its ``BINDINGS`` mapping."""
    errors: list[str] = []
    if not path.is_file():
        return {}, [f"bindings file not found: {path}"]
    module_name = f"_tower_clause_bindings_{abs(hash(path.resolve()))}"
    try:
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            return {}, [f"cannot load bindings module: {path}"]
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    except Exception as exc:  # noqa: BLE001 - report any import/exec failure
        return {}, [f"cannot load bindings {path}: {exc}"]
    bindings = getattr(module, BINDINGS_VAR, None)
    if not isinstance(bindings, dict):
        errors.append(f"bindings module must define a dict {BINDINGS_VAR}: {path}")
        return {}, errors
    return bindings, errors


def evaluate(root: Path, *, bindings_path=None, tests_dir=None) -> dict:
    """Run the coverage gate and return the JSON payload described in TASK.md."""
    root = Path(root)
    bindings_file = _resolve(root, bindings_path, DEFAULT_BINDINGS)
    tests_path = _resolve(root, tests_dir, DEFAULT_TESTS_DIR)

    clauses, spec_ids, errors = collect_clauses(root)
    tests, test_errors = collect_test_ids(tests_path)
    errors.extend(test_errors)
    bindings, binding_errors = load_bindings(bindings_file)
    errors.extend(binding_errors)

    clause_by_key: dict[str, dict] = {}
    for clause in clauses:
        key = f"{clause['spec']}/{clause['id']}"
        clause_by_key[key] = clause
        if clause["enforcement"] not in KNOWN_ENFORCEMENTS:
            errors.append(
                f"{key}: unknown enforcement {clause['enforcement']!r}")

    unknown: list[dict] = []
    for key in sorted(bindings):
        if not isinstance(key, str):
            errors.append(f"binding key must be a string, got {key!r}")
            continue
        if key not in clause_by_key:
            unknown.append({"kind": "unknown_clause", "clause": key})
            continue
        values = bindings[key]
        if not isinstance(values, list) or not all(
                isinstance(value, str) for value in values):
            errors.append(f"binding {key}: value must be a list of test ids")
            continue
        for test_id in values:
            if test_id not in tests:
                unknown.append({"kind": "unknown_test", "clause": key,
                                "test": test_id})

    tool_keys = sorted(key for key, clause in clause_by_key.items()
                       if clause["enforcement"] == TOOL)
    tool_gaps: list[str] = []
    covered = 0
    for key in tool_keys:
        values = bindings.get(key)
        bound = values if isinstance(values, list) else []
        if not bound:
            tool_gaps.append(key)
        elif any(value in tests for value in bound if isinstance(value, str)):
            covered += 1

    manual = sorted(key for key, clause in clause_by_key.items()
                    if clause["enforcement"] == REVIEW)
    owner = sorted(key for key, clause in clause_by_key.items()
                   if clause["enforcement"] == OWNER)
    ok = not tool_gaps and not unknown and not errors
    return {
        "ok": ok,
        "specs": len(spec_ids),
        "clauses": len(clauses),
        "tool_check": len(tool_keys),
        "covered": covered,
        "tool_gaps": tool_gaps,
        "manual": manual,
        "owner": owner,
        "unknown": unknown,
        "errors": errors,
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Check that every tool-check clause is bound to a real test")
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--bindings", default=None,
                        help="bindings module (default: tools/tests/clause_bindings.py)")
    parser.add_argument("--tests-dir", default=None,
                        help="test directory to scan (default: tools/tests)")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    if not root.exists():
        payload = {
            "ok": False, "specs": 0, "clauses": 0, "tool_check": 0,
            "covered": 0, "tool_gaps": [], "manual": [], "owner": [],
            "unknown": [], "errors": [f"root not found: {root}"],
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        raise SystemExit(2)
    result = evaluate(root, bindings_path=args.bindings, tests_dir=args.tests_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["ok"] else 2)


if __name__ == "__main__":
    main()
