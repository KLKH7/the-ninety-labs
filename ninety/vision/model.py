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


def load(weights: str | None = None, **kwargs):
    """RF-DETR Small, the only detector class we run: COCO weights, or our checkpoint at `weights`.

    The class is fixed here, not passed in, so no caller can load a size under a different license.
    """
    import rfdetr

    cls = rfdetr.RFDETRSmall
    if cls.size != "rfdetr-small":
        raise RuntimeError(f"rfdetr.RFDETRSmall reports size {cls.size!r}, not rfdetr-small")
    if weights is not None:
        kwargs["pretrain_weights"] = weights
    return cls(**kwargs)
