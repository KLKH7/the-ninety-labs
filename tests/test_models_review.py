"""The parts of the GitHub Models review that decide what the model sees and what gets posted."""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("models_review", ROOT / ".github/scripts/models_review.py")
review = importlib.util.module_from_spec(spec)
spec.loader.exec_module(review)


def chunk(path: str, size: int) -> str:
    head = f"diff --git a/{path} b/{path}\n"
    return head + "+" * (size - len(head))


def test_split_files_keeps_one_chunk_per_file():
    diff = chunk("a.py", 50) + "\n" + chunk("b.py", 50)
    assert [review.path_of(c) for c in review.split_files(diff)] == ["a.py", "b.py"]


def test_fit_keeps_whole_files_and_names_the_rest():
    chunks = [chunk("a.py", 100), chunk("big.py", 1000), chunk("c.py", 100)]
    kept, omitted = review.fit(chunks, 250)
    assert [review.path_of(c) for c in kept] == ["a.py", "c.py"]
    assert omitted == ["big.py"]


def test_hard_rules_come_from_section_4_of_agents_md():
    rules = review.hard_rules((ROOT / "AGENTS.md").read_text())
    assert "The repo is public" in rules
    assert "## 5" not in rules and "Working in the repo" not in rules


def test_comment_is_marked_and_says_what_was_not_reviewed():
    body = review.comment_body("No issues found.", "openai/gpt-4.1", "abcdef123456", ["big.py"])
    assert body.startswith(review.MARKER)
    assert "abcdef1" in body and "big.py" in body
