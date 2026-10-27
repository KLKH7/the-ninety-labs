"""The Foundry event check (ninety/vision/foundry_check.py) with a fake model: candidates from
positions, the side from code, the spend cap, and that frames go only to our Foundry client."""

import ast
import asyncio
from pathlib import Path

import pytest
from PIL import Image

from ninety import config
from ninety.vision import foundry_check as fc

SRC = Path(fc.__file__)


def clip_with(ball: dict[int, tuple[float, float]], n: int = 200, detected=None) -> fc.Clip:
    return fc.Clip(frames=list(range(n)), segments=[(0, n)], ball_px={}, ball=ball, detected=detected or [])


def test_a_ball_reaching_a_line_is_a_restart_candidate():
    ball = {f: (50.0, 30.0 + 0.2 * f) for f in range(200)}  # walks toward y = 68, crossing it near f 190
    got = [c for c in fc.candidates(clip_with(ball)) if c.family == "restart"]
    assert [c.why for c in got] == ["at a line"]
    assert 180 <= got[0].frame <= 190


def test_a_still_ball_in_the_goal_area_is_a_set_ball():
    ball = {f: (3.0, 34.0) for f in range(60)}
    got = fc.candidates(clip_with(ball, n=60))
    assert [c.why for c in got] == ["set ball"]


def test_a_still_ball_mid_pitch_is_not_a_candidate():
    assert fc.candidates(clip_with({f: (52.5, 20.0) for f in range(60)}, n=60)) == []


def test_a_fast_ball_toward_goal_is_a_shot_candidate_and_a_wide_one_is_not():
    toward = {f: (80.0 + 0.8 * f, 34.0) for f in range(20)}  # 72 km/h at the goal's centre
    assert [c.why for c in fc.candidates(clip_with(toward, n=20))] == ["fast toward goal"]
    wide = {f: (80.0 + 0.8 * f, 10.0) for f in range(20)}  # 24 m off the centre
    assert [c.why for c in fc.candidates(clip_with(wide, n=20)) if c.family == "shot"] == []
    slow = {f: (80.0 + 0.2 * f, 34.0) for f in range(20)}  # 18 km/h
    assert [c for c in fc.candidates(clip_with(slow, n=20)) if c.family == "shot"] == []


def test_candidates_of_a_family_merge_within_three_seconds():
    raw = [fc.Candidate("shot", i, i, "x", None) for i in (0, 10, 74, 76)]
    assert [c.index for c in fc.merge(raw)] == [0, 76]


def test_frames_stay_inside_the_candidates_segment():
    clip = fc.Clip(list(range(100)), [(0, 50), (50, 100)], {}, {}, [])
    assert fc.frame_indices(clip, fc.Candidate("restart", 40, 40, "x", None)) == [40, 49, 49]
    assert fc.frame_indices(clip, fc.Candidate("shot", 52, 52, "x", None)) == [50, 62, 82]


def test_the_side_is_codes_from_the_end_never_the_models():
    assert fc.side("corner", 104.0) == "home" and fc.side("corner", 1.0) == "away"
    assert fc.side("goal_kick", 104.0) == "away" and fc.side("goal_kick", 1.0) == "home"
    assert fc.side("shot", 90.0) == "home"
    assert fc.side("throw_in", 90.0) is None


def _row(index, label, conf, x=100.0):
    return fc.Checked(fc.Candidate("restart", index, index, "x", (x, 60.0)), [index], label, conf)


def test_code_counts_confident_labels_once_a_moment():
    clip = clip_with({}, n=2000)
    rows = [_row(0, "corner", 0.9), _row(100, "corner", 0.9), _row(400, "corner", 0.9),
            _row(500, "throw_in", 0.5), _row(600, "none", 0.99), _row(700, "shot", 0.7)]
    ev = fc.events_from(clip, rows)
    assert [(e["type"], e["restart"]) for e in ev] == [("set_piece", "corner"), ("set_piece", "corner"),
                                                       ("shot", None)]
    assert all(e["source"] == "foundry_check" for e in ev)
    assert ev[0]["team"] == "home" and ev[0]["confidence"] == 0.9


def _frames_clip():
    return fc.Clip(list(range(10)), [(0, 10)], {}, {}, [])


def _reader(indices):
    return {i: Image.new("RGB", (1280, 720), (30, 120, 40)) for i in indices}


def test_the_model_sees_only_the_fixed_instructions_and_the_frames():
    """No candidate reason, number, side, time or viewer text reaches the model."""
    sent = []

    class FakeClient:
        async def get_response(self, messages, options=None):
            sent.append((messages, options))

            class R:
                value = fc.Verdict(label="corner", confidence=0.8, seen="ball at the corner arc")
                text = ""
                usage_details = {"input_token_count": 600, "output_token_count": 20}

            return R()

    clip = _frames_clip()
    cand = fc.Candidate("restart", 2, 2, "SECRET-REASON 42 home", (104.0, 67.0))
    rows = asyncio.run(fc.check(clip, [cand], _reader, fc.foundry_classifier(FakeClient()), fc.Spend(0.5)))
    assert rows[0].label == "corner" and rows[0].tokens_in == 600
    (messages, options), = sent
    (msg,) = messages
    texts = [c.text for c in msg.contents if c.type == "text"]
    images = [c for c in msg.contents if c.type == "data"]
    assert texts == [fc.INSTRUCTIONS] and len(images) == 3
    assert all(c.additional_properties.get("detail") == "low" for c in images)
    assert options["temperature"] == 0.0 and options["response_format"] is fc.Verdict


def test_frames_are_downscaled_jpeg():
    data = fc.crop(Image.new("RGB", (1280, 720)), (1270.0, 5.0))
    im = Image.open(__import__("io").BytesIO(data))
    assert im.format == "JPEG" and im.size == (fc.OUT_W, fc.OUT_H)


def test_the_cap_stops_calls_before_spending_past_it():
    calls = []

    async def classify(images):
        calls.append(1)
        return fc.Verdict(label="none", confidence=0.9, seen=""), 10_000, 10

    clip = _frames_clip()
    cands = [fc.Candidate("restart", i, i, "x", None) for i in range(5)]
    spend = fc.Spend(cap_usd=0.0)
    rows = asyncio.run(fc.check(clip, cands, _reader, classify, spend, concurrency=1))
    assert calls == [] and all(r.error == "cap reached" for r in rows) and spend.usd == 0


def test_a_failed_call_is_logged_and_counts_as_no_event():
    async def classify(images):
        raise TimeoutError("slow")

    rows = asyncio.run(fc.check(_frames_clip(), [fc.Candidate("shot", 3, 3, "x", None)], _reader, classify,
                                fc.Spend(0.5)))
    assert rows[0].error.startswith("TimeoutError") and fc.events_from(_frames_clip(), rows) == []


def test_the_estimate_prices_images_and_prompt_at_the_higher_meter():
    est = fc.estimate(100)
    assert est["tokens_in"] == 100 * max(fc.prompt_tokens() + 3 * fc.IMAGE_TOKENS, fc.MEASURED_CALL_IN)
    assert 0 < est["usd"] < 0.1


def test_frames_go_only_to_our_foundry_project():
    """The module opens no network client of its own: the only model call is through the chat client
    built by ninety/agents/foundry.py on config.FOUNDRY_PROJECT, our own Foundry resource."""
    tree = ast.parse(SRC.read_text())
    imported = {n.names[0].name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import)} | {
        (n.module or "").split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert not imported & {"requests", "httpx", "urllib", "urllib3", "aiohttp", "socket", "http", "openai"}
    assert "foundry.chat_client(credential)" in SRC.read_text()
    assert config.FOUNDRY_PROJECT.startswith("https://ninety-labs-ai.services.ai.azure.com/")
    # ffmpeg decodes local files only
    assert "-i\", str(src)" in SRC.read_text()


def test_the_checker_reads_no_ground_truth():
    """It opens only live-path files; from ninety.eval it takes the price table alone."""
    tree = ast.parse(SRC.read_text())
    from_eval = {(n.module, a.name) for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)
                 and (n.module or "").startswith("ninety.eval") for a in n.names}
    assert {m for m, _ in from_eval} == {"ninety.eval.latency_cost"}
    opened = {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)
              and n.value.endswith((".json", ".jsonl"))}
    assert opened == {"clip.json", "observations.jsonl", "tracked.json", "detected.jsonl"}


@pytest.mark.parametrize("label", fc.LABELS)
def test_every_label_has_a_dedupe_or_is_none(label):
    assert label == "none" or label in fc.DEDUPE_S
