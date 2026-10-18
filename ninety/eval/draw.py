"""Draw scorer-aligned detection boxes as SVG overlays without changing source images."""

from __future__ import annotations

import argparse
import html
import json
import os
from collections.abc import Iterable
from pathlib import Path
from urllib.parse import quote

from ninety.eval.vision_score import (
    DEFAULT_THRESHOLD,
    flatten,
    frames_run,
    ground_truth,
    load_jsonl,
    match,
)

COLORS = {
    "truth": "#1683ff",
    "matched": "#16a34a",
    "missed": "#ef4444",
    "false": "#d946ef",
}


def _svg_box(box: Iterable[float], color: str, label: str, width: float = 3.0) -> str:
    x0, y0, x1, y1 = (float(value) for value in box)
    safe_label = html.escape(label)
    return (
        f'<rect x="{x0:g}" y="{y0:g}" width="{x1 - x0:g}" height="{y1 - y0:g}" '
        f'fill="none" stroke="{color}" stroke-width="{width:g}"/>'
        f'<text x="{x0 + 3:g}" y="{max(14.0, y0 + 14):g}" fill="{color}" '
        'font-family="sans-serif" font-size="14" font-weight="bold" '
        f'style="paint-order:stroke;stroke:#111827;stroke-width:3px">{safe_label}</text>'
    )


def _legend(top: int) -> str:
    entries = (
        ("truth", "ground truth", 16, 0),
        ("matched", "matched prediction", 300, 0),
        ("missed", "missed ground truth", 16, 1),
        ("false", "false prediction", 300, 1),
    )
    parts = ['<g font-family="sans-serif" font-size="14" font-weight="bold">']
    for kind, label, x, row in entries:
        y = top + 8 + row * 23
        parts.append(f'<rect x="{x}" y="{y}" width="16" height="16" fill="{COLORS[kind]}"/>')
        parts.append(f'<text x="{x + 23}" y="{y + 14}" fill="white">{html.escape(label)}</text>')
    parts.append("</g>")
    return "".join(parts)


def draw(clip: Path, detected: Path, output: Path, threshold: float = DEFAULT_THRESHOLD) -> dict:
    """Write one SVG overlay per frame the detector ran on and return match/error counts.

    Like the scorer, a frame is run when ``detected`` has a line for it (an empty list still
    counts). Frames without a line are not drawn, and their labels are not misses.
    """
    frames = load_jsonl(clip / "frames.jsonl")
    rows = load_jsonl(detected)
    run = frames_run(rows)
    frame_by_number = {int(frame["frame"]): frame for frame in frames}
    if unknown := sorted(run - frame_by_number.keys()):
        raise ValueError(f"detections name frames not in frames.jsonl: {unknown[:5]}")
    detections = [
        detection
        for detection in flatten(rows)
        if float(detection.get("score", 0.0)) >= threshold
    ]
    labels = [label for label in ground_truth(frames) if label["frame"] in run]
    pairs = match(labels, detections, threshold=threshold)
    matched_truth = {pair["truth"] for pair in pairs}
    matched_detection = {pair["detection"] for pair in pairs}
    output_dir = output.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    counts = {"frames": 0, "matched": len(pairs), "missed": 0, "false": 0}

    for frame_number in sorted(run):
        frame = frame_by_number[frame_number]
        camera = frame.get("camera", {})
        width, height = int(camera.get("width", 1280)), int(camera.get("height", 720))
        image = frame.get("image")
        if not image:
            raise ValueError(f"frame {frame_number} has no image path")
        source = (clip / image).resolve()
        if not source.is_file():
            raise FileNotFoundError(source)
        source_reference = html.escape(quote(os.path.relpath(source, output_dir), safe="/"))
        legend_top = height - 54
        elements = [
            f'<image href="{source_reference}" x="0" y="0" width="{width}" height="{height}"/>',
            f'<rect x="0" y="{legend_top}" width="100%" height="54" fill="#111827" fill-opacity="0.8"/>',
            _legend(legend_top),
        ]
        for truth_index, label in enumerate(labels):
            if label["frame"] != frame_number:
                continue
            if truth_index in matched_truth:
                elements.append(_svg_box(label["bbox"], COLORS["truth"], f'TRUTH {label["cls"]}', 4.0))
            else:
                counts["missed"] += 1
                elements.append(_svg_box(label["bbox"], COLORS["missed"], f'MISSED {label["cls"]}'))
        for detection_index, detection in enumerate(detections):
            if detection["frame"] != frame_number:
                continue
            if detection_index in matched_detection:
                elements.append(
                    _svg_box(detection["bbox"], COLORS["matched"], f'MATCH {detection["cls"]}', 1.5)
                )
            else:
                counts["false"] += 1
                elements.append(_svg_box(detection["bbox"], COLORS["false"], f'FALSE {detection["cls"]}'))

        output_path = output_dir / f"{frame_number:05d}.svg"
        output_path.write_text(
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
            f'width="{width}" height="{height}">'
            + "".join(elements)
            + "</svg>\n"
        )
        counts["frames"] += 1
    return counts


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Draw scorer-matched boxes over source JPEGs as SVG files; source images are unchanged."
    )
    parser.add_argument("clip", type=Path, help="clip directory containing frames.jsonl and source images")
    parser.add_argument(
        "detected",
        type=Path,
        help="detection JSONL with per-frame detections or flat frame/cls/bbox/score records",
    )
    parser.add_argument("--out", type=Path, required=True, help="explicit directory for SVG overlays")
    parser.add_argument(
        "--threshold",
        type=float,
        default=DEFAULT_THRESHOLD,
        help=f"minimum detection score (default: {DEFAULT_THRESHOLD})",
    )
    args = parser.parse_args(argv)
    print(json.dumps(draw(args.clip, args.detected, args.out, args.threshold), sort_keys=True))


if __name__ == "__main__":
    main()
