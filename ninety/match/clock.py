"""Match-clock formatting shared by the renderer and agent-facing facts."""

from __future__ import annotations


def match_clock(t: float) -> str:
    """Return the elapsed clock shown by the scorebug, flooring both components."""
    return f"{int(t // 60):02d}:{int(t % 60):02d}"
