"""The one detector we run: RF-DETR Small, at the rfdetr version pinned in pyproject.toml.

Every `detections.jsonl` line names its model; build that name with `model()` so the size and
version written there always match what is installed.

Only the Apache-2.0 sizes are allowed (AGENTS.md); we use Small. rfdetr is in the optional
`vision` dependency group, so install it with `uv sync --group vision`.
"""

from __future__ import annotations

from ninety.vision.detections import Model

NAME = "rf-detr"
SIZE = "small"  # rfdetr.RFDETRSmall
VERSION = "1.11.2"  # must equal the `rfdetr==` pin in pyproject.toml's vision group


def model(checkpoint: str = "coco") -> Model:
    """The `model` field of a detections.jsonl line: "coco" for the baseline, or our checkpoint."""
    return Model(name=NAME, size=SIZE, version=VERSION, checkpoint=checkpoint)
