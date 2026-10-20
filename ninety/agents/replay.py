"""Recorded model answers, so a workflow can run again without Azure.

A recording is the list of every model answer from one live run, in the order they were asked. A
replay runs the real workflow and code checks and answers each model call from the list: the next
answer must be for the same role and the exact same prompt, or the replay stops. It never pairs an
old answer with a new question, and it is never made tolerant of a changed prompt: re-record
instead (docs/LESSONS.md, lessons 32 and 44).

Two formats:

- `Recording`, format `REPLAY_FORMAT` (3): the thin slice (ninety/agents/slice.py), one Analyst and
  one Judge, with the match events the live run checked claims against (lesson 80). Its files in
  replays/ load and replay byte for byte as before the move.
- `WorkflowRecording`, format `WORKFLOW_REPLAY_FORMAT` (1): any workflow and any roles. It also
  stores the commit it ran on and the published agent versions it called (`pins`), so a replay
  says what it is a replay of.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path

from ninety.agents.factcheck import Claim, Verdict

REPLAY_FORMAT = 3
WORKFLOW_REPLAY_FORMAT = 1

Ask = Callable[[str], Awaitable[str]]
Judge = Callable[[Claim, list[dict]], Awaitable[Verdict]]


@dataclass
class Turn:
    """One model answer: the Analyst's raw reply, or the Judge's verdict as JSON."""

    role: str
    prompt: str
    response: str


@dataclass
class Recording:
    """The models' answers from one live run, enough to replay it without Azure."""

    minute: int
    seed: int
    minutes: float
    plant: bool
    model: str
    recorded_at: str
    turns: list[Turn]
    events: list[dict]  # what the fact-checker checked claims against in the live run

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"format": REPLAY_FORMAT, **asdict(self)}, indent=2) + "\n")

    @classmethod
    def load(cls, path: str | Path) -> Recording:
        data = json.loads(Path(path).read_text())
        found = data.pop("format", None)
        if found != REPLAY_FORMAT:
            raise ValueError(
                f"{path}: format {found} slice recording, this code replays format {REPLAY_FORMAT}"
                + (" (format 2 has no match events): record it again with --record" if found == 2 else "")
            )
        data["turns"] = [Turn(**t) for t in data["turns"]]
        return cls(**data)


@dataclass
class WorkflowRecording:
    """Every model answer from one live run of any workflow, with what it ran on.

    `inputs` is what the workflow was started with (seed, minutes, moment ids), `commit` the git
    commit, and `pins` each published agent's version (`{"ninety-tactician": "3"}`)."""

    workflow: str
    commit: str
    pins: dict[str, str]
    inputs: dict
    recorded_at: str
    turns: list[Turn] = field(default_factory=list)

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"format": WORKFLOW_REPLAY_FORMAT, **asdict(self)}, indent=2) + "\n")

    @classmethod
    def load(cls, path: str | Path) -> WorkflowRecording:
        data = json.loads(Path(path).read_text())
        if data.pop("format", None) != WORKFLOW_REPLAY_FORMAT:
            raise ValueError(f"{path}: not a format {WORKFLOW_REPLAY_FORMAT} workflow recording")
        data["turns"] = [Turn(**t) for t in data["turns"]]
        return cls(**data)


class ReplayMismatch(RuntimeError):
    pass


def judge_prompt(claim: Claim) -> str:
    """What identifies a Judge call in a recording: the claim and the ids it cites."""
    return json.dumps({"text": claim.text, "evidence": claim.evidence})


class Replayer:
    """Answers each call with the next recorded answer, which must be for the same role and the
    exact same prompt, and refuses a call it never saw."""

    def __init__(self, turns: list[Turn]):
        self._queue = list(turns)

    @property
    def remaining(self) -> int:
        """Recorded answers not asked for yet: a finished replay that leaves some ran differently."""
        return len(self._queue)

    def answer(self, role: str, prompt: str) -> str:
        if not self._queue:
            raise ReplayMismatch(f"the recording has no {role} answer for: {prompt!r}")
        turn = self._queue.pop(0)
        if (turn.role, turn.prompt) != (role, prompt):
            raise ReplayMismatch(
                f"call changed since recording: {turn.role} {turn.prompt!r} -> {role} {prompt!r}"
            )
        return turn.response

    def ask(self, role: str) -> Ask:
        """A text model for `role`: prompt in, raw reply out."""

        async def ask(prompt: str) -> str:
            return self.answer(role, prompt)

        return ask

    def judge(self, role: str = "judge") -> Judge:
        """A Judge: the claim identifies the call, the answer is the recorded Verdict."""

        async def judge_replay(claim: Claim, evidence: list[dict]) -> Verdict:
            return Verdict(**json.loads(self.answer(role, judge_prompt(claim))))

        return judge_replay


def replayer(turns: list[Turn]) -> tuple[Ask, Judge]:
    """The slice's pair: the Analyst and the Judge, answered from one recording in order."""
    replay = Replayer(turns)
    return replay.ask("analyst"), replay.judge()
