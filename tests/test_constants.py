"""A module-level name assigned twice silently replaces the first value: the engine's cover
distance was once overwritten this way by an unrelated constant with the same name."""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def assigned_twice(source: str) -> dict[str, list[int]]:
    """Names assigned more than once at the top level of a module, with their lines."""
    lines: dict[str, list[int]] = {}
    for node in ast.parse(source).body:
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets = [node.target]
        else:
            continue
        for target in targets:
            for name in ast.walk(target):
                if isinstance(name, ast.Name):
                    lines.setdefault(name.id, []).append(node.lineno)
    return {name: at for name, at in lines.items() if len(at) > 1}


def test_the_check_finds_a_name_assigned_twice():
    assert assigned_twice("A = 1\nB, A = 2, 3\n") == {"A": [1, 2]}
    assert assigned_twice("A = 1\nif True:\n    A = 2\n") == {}  # a branch is a deliberate choice


def test_no_module_assigns_a_top_level_name_twice():
    found = {
        str(path.relative_to(ROOT)): twice
        for path in sorted((ROOT / "ninety").rglob("*.py"))
        if (twice := assigned_twice(path.read_text()))
    }
    assert found == {}
