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
    (Path(out) / "clip.json").write_text(json.dumps({"seed": seed, "overrides": overrides}))


def test_config_reads_seeds_and_overrides():
    cfg = job.job_config(ENV | {"NINETY_SET": "occlusion=crowded; kit_contrast=low", "NINETY_SECONDS": "4"})
    assert cfg["seeds"] == [1, 2, 3]
    assert cfg["overrides"] == {"occlusion": "crowded", "kit_contrast": "low"}
    assert cfg["seconds"] == 4.0 and cfg["container"] == "renders"


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


def test_uploads_passing_clips_with_clip_json_last(tmp_path, monkeypatch):
    monkeypatch.setattr(job, "check_clip", lambda d: {"passed": {"labels_complete": True}})
    c = FakeContainer()
    done = job.run_job(job.job_config(ENV), c, fake_render, fake_browser, tmp_path)
    assert done == {"uploaded": [1, 2, 3], "skipped": [], "failed": []}
    seed1 = [n for n in c.order if n.startswith("v1/train/seed1/")]
    assert set(seed1) == {"v1/train/seed1/images/00000.jpg", "v1/train/seed1/frames.jsonl",
                          "v1/train/seed1/clip.json"}
    assert seed1[-1] == "v1/train/seed1/clip.json"
    assert not list(tmp_path.iterdir())  # local copies removed after upload


def test_a_finished_seed_is_skipped_on_retry(tmp_path, monkeypatch):
    monkeypatch.setattr(job, "check_clip", lambda d: {"passed": {"labels_complete": True}})
    c = FakeContainer(existing=["v1/train/seed2/clip.json"])
    done = job.run_job(job.job_config(ENV), c, fake_render, fake_browser, tmp_path)
    assert done["skipped"] == [2] and done["uploaded"] == [1, 3]


def test_a_clip_that_fails_its_checks_is_reported_not_uploaded(tmp_path, monkeypatch):
    monkeypatch.setattr(job, "check_clip", lambda d: {"passed": {"labels_complete": "seed2" not in str(d)}})
    c = FakeContainer()
    done = job.run_job(job.job_config(ENV), c, fake_render, fake_browser, tmp_path)
    assert done["failed"] == [2]
    assert "v1/failed/seed2.json" in c.store
    assert not any(n.startswith("v1/train/seed2/") for n in c.store)
