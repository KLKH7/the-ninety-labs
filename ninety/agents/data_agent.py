"""The Data agent: turns the Vision Auditor's failure clusters into render requests on the queue
the event-driven render job reads (infra/main.bicep), so the detector gets more footage of exactly
what it fails on. Code, not a model: every number and render setting here is decided by rules.

    uv run python -m ninety.agents.data_agent runs/round1/clusters.json --first-seed 2001 --budget 40
    ... --enqueue          # also send the requests to the render queue (needs uv sync --group render-job)

The input is the Auditor's handoff (docs/TEAM.md, Wed Oct 21):

    {"round": "round1",
     "clusters": [{"name": "ball hidden in a crowded box", "misses": 37,
                   "render": {"occlusion": "crowded"}}, ...]}

Rules:
- Every cluster's render settings must be ones the renderer has and accepts
  (ninety.render.params.sample_params validates them; a planned knob is refused).
- The budget is split by misses, largest remainder first, so the split is exact and reproducible;
  a cluster with misses gets at least one clip while the budget lasts.
- When the handoff states clips per cluster (the Vision Auditor's clusters.json does), they must
  be this split, or the plan is refused. A typed handoff is also checked on receipt, not only by
  its writer: the schema, every source seed a training seed, each cluster's render setting the one
  failure_clusters.RENDER gives its situation, and its seed range the one this split gives it.
- Seeds are consecutive from --first-seed and must all be training seeds: a targeted round never
  touches the fixed test set, so its before and after scores stay honest.
- Every request names the commit to render with; the job refuses any other, so a round comes from
  one engine version. The commit must be pushed, since the job fetches it from GitHub.

Writes the plan to runs/<round>/requests.json (counts per cluster and every request) before
anything is enqueued, so what was asked for is on record.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from ninety.agents.contracts import schema_validator
from ninety.render.params import sample_params
from ninety.render.splits import check_seed
from ninety.vision.failure_clusters import RENDER

PER_REQUEST = 10  # clips per job execution: about 50 minutes at the measured 5 minutes a clip
SECONDS = 10.0


def allocate(clusters: list[dict], budget: int) -> list[int]:
    """Clips per cluster, proportional to misses, summing to the budget (largest remainder)."""
    misses = [max(0, int(c["misses"])) for c in clusters]
    total = sum(misses)
    if budget < 0:
        raise ValueError("budget must be non-negative")
    if total == 0:
        return [0] * len(clusters)
    quotas = [budget * m / total for m in misses]
    counts = [int(q) for q in quotas]
    # At least one clip for every cluster that has misses, while the budget allows.
    for i in sorted(range(len(clusters)), key=lambda i: -misses[i]):
        if misses[i] and counts[i] == 0 and sum(counts) < budget:
            counts[i] = 1
    # The rest goes one clip at a time to the cluster furthest below its share (ties: more misses).
    while sum(counts) < budget:
        i = max(
            (i for i in range(len(clusters)) if misses[i]),
            key=lambda i: (quotas[i] - counts[i], misses[i], -i),
        )
        counts[i] += 1
    return counts


def render_set(render: dict) -> str:
    """The cluster's settings as the job's NINETY_SET string, after the renderer validates them."""
    sample_params(1, **render)  # raises on an unknown knob, a bad value or a planned one
    return ";".join(f"{k}={str(v).lower() if isinstance(v, bool) else v}" for k, v in sorted(render.items()))


def check_typed(handoff: dict, counts: list[int], first_seed: int) -> None:
    """The Vision Auditor's clusters.json, checked on receipt: the schema, training seeds only, the
    renderer's setting for each situation, and the clips and seeds this agent would give it."""
    schema_validator("failure_clusters").validate(handoff)
    for s in handoff["source"]["seeds"]:
        check_seed(s, "train")
    if handoff["first_seed"] != first_seed:
        raise ValueError(f"handoff was split from seed {handoff['first_seed']}, not {first_seed}")
    seed = first_seed
    for c, n in zip(handoff["clusters"], counts, strict=True):
        if c["render"] != RENDER[c["situation"]]:
            raise ValueError(f"{c['name']}: render {c['render']} is not the setting for {c['situation']!r}")
        want = [seed, seed + n - 1] if n else None
        if c["seeds"] != want:
            raise ValueError(f"{c['name']}: seeds {c['seeds']}, this split gives {want}")
        seed += n


def plan(
    handoff: dict,
    budget: int,
    first_seed: int,
    commit: str,
    per_request: int = PER_REQUEST,
    seconds: float = SECONDS,
) -> dict:
    run = handoff["round"]
    if not str(run).replace("-", "").replace("_", "").isalnum():
        raise ValueError(f"round must be letters, digits, '-' or '_', not {run!r}")
    clusters = handoff["clusters"]
    sets = [render_set(c.get("render") or {}) for c in clusters]
    counts = allocate(clusters, budget)
    # The Vision Auditor writes the clips it expects (schemas/failure_clusters.schema.json); a
    # handoff that disagrees with this split was made with another budget or another rule.
    stated = [c.get("clips") for c in clusters]
    if any(n is not None for n in stated) and stated != counts:
        raise ValueError(f"handoff asks for {stated} clips, the budget of {budget} splits as {counts}")
    if "source" in handoff:  # the typed shape (schemas/failure_clusters.schema.json)
        check_typed(handoff, counts, first_seed)
    requests, seed = [], first_seed
    for cluster, count, settings in zip(clusters, counts, sets, strict=True):
        for start in range(seed, seed + count, per_request):
            n = min(per_request, seed + count - start)
            for s in range(start, start + n):
                check_seed(s, "train")
            requests.append(
                {
                    "run": run,
                    "first_seed": start,
                    "count": n,
                    "set": settings,
                    "seconds": seconds,
                    "commit": commit,
                    "reason": f"{cluster['name']} ({cluster['misses']} misses)",
                }
            )
        seed += count
    return {
        "round": run,
        "commit": commit,
        "budget": budget,
        "first_seed": first_seed,
        "clusters": [
            {"name": c["name"], "misses": c["misses"], "set": s, "clips": n}
            for c, s, n in zip(clusters, sets, counts, strict=True)
        ],
        "requests": requests,
    }


def enqueue(requests: list[dict], queue_url: str, queue: str = "render-requests") -> None:
    from azure.identity import DefaultAzureCredential
    from azure.storage.queue import QueueClient

    client = QueueClient(queue_url, queue, credential=DefaultAzureCredential())
    for request in requests:
        client.send_message(json.dumps(request))


def pushed_head() -> str:
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()
    remotes = subprocess.run(
        ["git", "branch", "-r", "--contains", head], capture_output=True, text=True
    ).stdout
    if not remotes.strip():
        raise SystemExit(f"push {head} first: the render job fetches the commit from GitHub")
    return head


def main() -> None:
    ap = argparse.ArgumentParser(description="Failure clusters to render requests for a targeted round.")
    ap.add_argument("clusters", type=Path, help="the Vision Auditor's clusters.json")
    ap.add_argument("--first-seed", type=int, required=True, help="first training seed of this round")
    ap.add_argument("--budget", type=int, required=True, help="clips to render in this round")
    ap.add_argument("--commit", help="engine commit to render with (default: HEAD, which must be pushed)")
    ap.add_argument("--seconds", type=float, default=SECONDS, help="clip length")
    ap.add_argument("--enqueue", action="store_true", help="send the requests to the render queue")
    ap.add_argument("--queue-url", help="https://<account>.queue.core.windows.net (default: from azd env)")
    args = ap.parse_args()
    handoff = json.loads(args.clusters.read_text())
    result = plan(handoff, args.budget, args.first_seed, args.commit or pushed_head(), seconds=args.seconds)
    out = Path("runs") / result["round"] / "requests.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    for c in result["clusters"]:
        print(f"{c['clips']:4d} clips  {c['name']}  [{c['set'] or 'no overrides'}]")
    print(f"{len(result['requests'])} requests written to {out}")
    if args.enqueue:
        url = (
            args.queue_url
            or subprocess.run(
                ["azd", "env", "get-value", "RENDER_QUEUE_URL"], capture_output=True, text=True, check=True
            ).stdout.strip()
        )
        enqueue(result["requests"], url)
        print(f"enqueued {len(result['requests'])} requests to {url}")


if __name__ == "__main__":
    main()
