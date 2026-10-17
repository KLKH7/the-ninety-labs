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
            # Only names bound here: `a, b = ...` binds a and b; `x.y = ...` and `d[k] = ...` bind none.
            stack = [target]
            while stack:
                t = stack.pop()
                if isinstance(t, ast.Name):
                    lines.setdefault(t.id, []).append(node.lineno)
                elif isinstance(t, (ast.Tuple, ast.List)):
                    stack.extend(t.elts)
                elif isinstance(t, ast.Starred):
                    stack.append(t.value)
    return {name: at for name, at in lines.items() if len(at) > 1}


def test_the_check_finds_a_name_assigned_twice():
    assert assigned_twice("A = 1\nB, A = 2, 3\n") == {"A": [1, 2]}
    assert assigned_twice("A = 1\nif True:\n    A = 2\n") == {}  # a branch is a deliberate choice
    assert assigned_twice("x.A = 1\nx.A = 2\nd[k] = 1\nd[k] = 2\n") == {}  # these bind no name
    assert assigned_twice("a, *b = 1, 2\nb = 3\n") == {"b": [1, 2]}


def test_no_module_assigns_a_top_level_name_twice():
    found = {
        str(path.relative_to(ROOT)): twice
        for path in sorted((ROOT / "ninety").rglob("*.py"))
        if (twice := assigned_twice(path.read_text()))
    }
    assert found == {}
