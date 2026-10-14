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


def test_prepare_writes_the_prompt_files_and_outputs(tmp_path, monkeypatch):
    diff = chunk("a.py", 100) + "\n" + chunk("big.py", 1000)
    agents = "## 4. Hard rules\n\n- **The repo is public.**\n\n## 5. Working in the repo\n"
    monkeypatch.setattr(review, "git", lambda *args: diff if args[0] == "diff" else agents)
    output = tmp_path / "output"
    monkeypatch.setenv("BASE_SHA", "b" * 40)
    monkeypatch.setenv("HEAD_SHA", "h" * 40)
    monkeypatch.setenv("REVIEW_DIR", str(tmp_path / "review"))
    monkeypatch.setenv("MAX_DIFF_CHARS", "500")
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    assert review.prepare() == 0
    prompt = (tmp_path / "review/prompt.txt").read_text()
    assert "The repo is public" in prompt and "a/a.py" in prompt and "big.py" not in prompt
    assert (tmp_path / "review/system.txt").read_text() == review.INSTRUCTIONS
    assert output.read_text() == "reviewable=true\nomitted=big.py\n"


def post_env(tmp_path, monkeypatch, answer: str, existing: list[dict]) -> list[tuple]:
    calls = []

    def fake_request(url, token, body=None, method="GET"):
        calls.append((method, url, body))
        return existing if method == "GET" else {}

    monkeypatch.setattr(review, "request", fake_request)
    (tmp_path / "answer.md").write_text(answer)
    for key, value in {
        "GITHUB_TOKEN": "t",
        "REPO": "o/r",
        "PR_NUMBER": "7",
        "HEAD_SHA": "abcdef123456",
        "MODEL": "openai/gpt-4.1",
        "RESPONSE_FILE": str(tmp_path / "answer.md"),
        "OMITTED": "big.py",
    }.items():
        monkeypatch.setenv(key, value)
    assert review.post() == 0
    return calls


def test_post_creates_the_comment_once_then_updates_it(tmp_path, monkeypatch):
    calls = post_env(tmp_path, monkeypatch, "No issues found.", existing=[])
    assert calls[-1][0] == "POST" and calls[-1][1].endswith("/issues/7/comments")
    assert "big.py" in calls[-1][2]["body"]
    mine = {"id": 99, "body": review.MARKER + "\nold"}
    calls = post_env(tmp_path, monkeypatch, "No issues found.", existing=[{"id": 1, "body": "hi"}, mine])
    assert calls[-1][0] == "PATCH" and calls[-1][1].endswith("/issues/comments/99")


def test_post_skips_an_empty_answer(tmp_path, monkeypatch):
    assert post_env(tmp_path, monkeypatch, "  \n", existing=[]) == []
