"""The render job's config, resume and upload rules, with a fake container and a fake renderer."""

import json
from contextlib import contextmanager
from pathlib import Path

import pytest

from ninety.render import job

ENV = {
    "NINETY_RUN": "v1",
    "NINETY_FIRST_SEED": "1",
    "NINETY_COUNT": "3",
    "AZURE_STORAGE_BLOB_URL": "https://example.blob.core.windows.net/",
}


class FakeBlob:
    def __init__(self, store, name):
        self.store, self.name = store, name

    def exists(self):
        return self.name in self.store


class FakeContainer:
    def __init__(self, existing=()):
        self.store = {n: b"" for n in existing}
        self.order = []

    def get_blob_client(self, name):
        return FakeBlob(self.store, name)

    def upload_blob(self, name, data, overwrite=False):
        self.store[name] = data if isinstance(data, bytes) else data.read()
        self.order.append(name)


@contextmanager
def fake_browser():
    yield "page", "fake"


def fake_render(seed, out, seconds, overrides, page):
    (Path(out) / "images").mkdir(parents=True)
    (Path(out) / "images" / "00000.jpg").write_bytes(b"jpg")
    (Path(out) / "frames.jsonl").write_text("{}\n")
    (Path(out) / "events.jsonl").write_text("{}\n")
    (Path(out) / "clip.json").write_text(json.dumps({"seed": seed, "overrides": overrides}))


def test_config_reads_seeds_and_overrides():
    cfg = job.job_config(ENV | {"NINETY_SET": "occlusion=crowded; kit_contrast=low", "NINETY_SECONDS": "4"})
    assert cfg["seeds"] == [1, 2, 3]
    assert cfg["overrides"] == {"occlusion": "crowded", "kit_contrast": "low"}
    assert cfg["seconds"] == 4.0 and cfg["container"] == "renders" and cfg["truth_container"] == "truth"


@pytest.mark.parametrize(
    "change",
    [
        {"NINETY_RUN": ""},
        {"NINETY_RUN": "../x"},
        {"NINETY_COUNT": "0"},
        {"NINETY_FIRST_SEED": "900001", "NINETY_COUNT": "1"},  # a test seed
        {"NINETY_FIRST_SEED": "899999", "NINETY_COUNT": "2"},  # runs into the reserved range
    ],
)
def test_config_refuses_bad_input_and_evaluation_seeds(change):
    with pytest.raises(ValueError):
        job.job_config(ENV | change)


class Log:
    """Both containers write to one log, so the test sees the order across them."""

    def __init__(self):
        self.order = []


def containers(existing=()):
    log = Log()
    clips, truth = FakeContainer(existing), FakeContainer()
    for c, label in ((clips, "renders"), (truth, "truth")):
        upload = c.upload_blob
        c.upload_blob = lambda name, data, overwrite=False, upload=upload, label=label: (
            log.order.append(f"{label}:{name}"),
            upload(name, data, overwrite),
        )
    return clips, truth, log


def test_uploads_passing_clips_with_clip_json_last(tmp_path, monkeypatch):
    monkeypatch.setattr(job, "check_clip", lambda d: {"passed": {"labels_complete": True}})
    c, truth, log = containers()
    done = job.run_job(job.job_config(ENV), c, fake_render, fake_browser, tmp_path, truth)
    assert done == {"uploaded": [1, 2, 3], "skipped": [], "failed": []}
    seed1 = [n for n in log.order if "/seed1/" in n]
    assert set(seed1) == {
        "renders:v1/train/seed1/images/00000.jpg",
        "truth:v1/train/seed1/frames.jsonl",
        "truth:v1/train/seed1/events.jsonl",
        "renders:v1/train/seed1/clip.json",
    }
    # clip.json marks the clip complete, so it lands after everything, truth included.
    assert seed1[-1] == "renders:v1/train/seed1/clip.json"
    assert not list(tmp_path.iterdir())  # local copies removed after upload


def test_ground_truth_never_lands_in_the_renders_container(tmp_path, monkeypatch):
    monkeypatch.setattr(job, "check_clip", lambda d: {"passed": {"labels_complete": True}})
    c, truth, _ = containers()
    job.run_job(job.job_config(ENV), c, fake_render, fake_browser, tmp_path, truth)
    assert not [n for n in c.store if n.endswith(job.TRUTH_FILES)]
    assert sorted(n.rsplit("/", 1)[1] for n in truth.store) == sorted(job.TRUTH_FILES * 3)


def fake_render_with_views(seed, out, seconds, overrides, page):
    fake_render(seed, out, seconds, overrides, page)
    for name in ("tac-l", "tac-r"):
        view = Path(out) / "views" / name
        (view / "images").mkdir(parents=True)
        (view / "images" / "00000.jpg").write_bytes(b"jpg")
        (view / "frames.jsonl").write_text("{}\n")
        (view / "events.jsonl").write_text("{}\n")
        (view / "clip.json").write_text("{}")


def test_a_views_answer_key_is_sealed_with_the_clips(tmp_path, monkeypatch):
    # Each view folder holds its own frames.jsonl and events.jsonl: true positions, boxes and events,
    # the answer key as much as the clip's own. In the readable renders container they would sit
    # beside vision's input (lesson 192). Fails on a seal that matched only the clip's top level.
    monkeypatch.setattr(job, "check_clip", lambda d: {"passed": {"labels_complete": True}})
    c, truth, log = containers()
    job.run_job(job.job_config(ENV), c, fake_render_with_views, fake_browser, tmp_path, truth)
    assert not [n for n in c.store if n.endswith(job.TRUTH_FILES)]
    assert "truth:v1/train/seed1/views/tac-l/frames.jsonl" in log.order
    assert "renders:v1/train/seed1/views/tac-r/images/00000.jpg" in log.order
    assert len(truth.store) == 3 * 3 * len(job.TRUTH_FILES)  # the clip and its two views, three seeds


def test_a_finished_seed_is_skipped_on_retry(tmp_path, monkeypatch):
    monkeypatch.setattr(job, "check_clip", lambda d: {"passed": {"labels_complete": True}})
    c, truth, _ = containers(existing=["v1/train/seed2/clip.json"])
    done = job.run_job(job.job_config(ENV), c, fake_render, fake_browser, tmp_path, truth)
    assert done["skipped"] == [2] and done["uploaded"] == [1, 3]


def test_a_clip_that_fails_its_checks_is_reported_not_uploaded(tmp_path, monkeypatch):
    monkeypatch.setattr(job, "check_clip", lambda d: {"passed": {"labels_complete": "seed2" not in str(d)}})
    c, truth, _ = containers()
    done = job.run_job(job.job_config(ENV), c, fake_render, fake_browser, tmp_path, truth)
    assert done["failed"] == [2]
    assert "v1/failed/seed2.json" in c.store
    assert not any(n.startswith("v1/train/seed2/") for n in c.store)


class FakeMessage:
    def __init__(self, content, dequeue_count=1):
        self.content, self.dequeue_count = content, dequeue_count


class FakeQueue:
    def __init__(self, messages=()):
        self.messages, self.sent, self.deleted = list(messages), [], []

    def receive_messages(self, max_messages, visibility_timeout):
        assert visibility_timeout > 4 * 3600  # outlasts the job's replica timeout
        return self.messages[:max_messages]

    def delete_message(self, message):
        self.deleted.append(message)

    def send_message(self, content):
        self.sent.append(json.loads(content))


QUEUE_ENV = {"AZURE_STORAGE_BLOB_URL": "https://example.blob.core.windows.net/", "NINETY_COMMIT": "abc123"}
REQUEST = {
    "run": "round1",
    "first_seed": 2001,
    "count": 2,
    "set": "occlusion=crowded",
    "seconds": 10,
    "commit": "abc123",
    "reason": "crowded box (37 misses)",
}


def test_a_queued_request_is_rendered_then_removed():
    ran = []
    queue, failed = FakeQueue([FakeMessage(json.dumps(REQUEST))]), FakeQueue()
    assert job.take_request(queue, failed, QUEUE_ENV, ran.append) == "done"
    assert ran[0]["seeds"] == [2001, 2002] and ran[0]["overrides"] == {"occlusion": "crowded"}
    assert queue.deleted and not failed.sent


def test_an_empty_queue_is_not_an_error():
    assert job.take_request(FakeQueue(), FakeQueue(), QUEUE_ENV, lambda cfg: None) == "queue empty"


@pytest.mark.parametrize(
    "request_",
    [
        REQUEST | {"commit": "other"},  # rendered with another engine: refused, never retried
        REQUEST | {"first_seed": 900001},  # the fixed test set
        "not json",
    ],
)
def test_a_bad_request_is_set_aside_at_once(request_):
    content = request_ if isinstance(request_, str) else json.dumps(request_)
    queue, failed, ran = FakeQueue([FakeMessage(content)]), FakeQueue(), []
    assert job.take_request(queue, failed, QUEUE_ENV, ran.append).startswith("failed for good")
    assert not ran and queue.deleted and failed.sent[0]["request"] == content


def test_a_crash_is_retried_once_then_set_aside():
    def crash(cfg):
        raise RuntimeError("browser crashed")

    first = FakeQueue([FakeMessage(json.dumps(REQUEST), dequeue_count=1)])
    failed = FakeQueue()
    assert job.take_request(first, failed, QUEUE_ENV, crash).startswith("failed, will retry")
    assert not first.deleted and not failed.sent  # it becomes visible again for the next execution
    second = FakeQueue([FakeMessage(json.dumps(REQUEST), dequeue_count=job.MAX_ATTEMPTS)])
    assert job.take_request(second, failed, QUEUE_ENV, crash).startswith("failed for good")
    assert second.deleted and "browser crashed" in failed.sent[0]["error"]
