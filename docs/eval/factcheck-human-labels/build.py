# ruff: noqa: E501  (the labelling page is one HTML document, kept readable as written)
"""Build the blind labelling page for the fact-checker, by RULE.md (fixed before the run was read).

    uv run python docs/eval/factcheck-human-labels/build.py docs/eval/fact-checker.json

Writes items.json (what the page shows), key.json (each item's stratum and the checker's verdict:
never loaded by the page) and index.html beside this file.
"""

from __future__ import annotations

import asyncio
import html
import json
import random
import re
import sys
import warnings
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = Path.cwd()
VISION = ROOT / "runs" / "demo-8080-1d0390be-vision"  # the 8080 dry run's vision output (not committed)
N = {"passed": 8, "rejected by code": 5, "rejected by the Judge": 6, "held": 3, "rewritten": 3}
SAMPLE_SEED, ORDER_SEED = 20261025, 25102026

KIND = {"pass": "Pass", "shot": "Shot", "tackle": "Tackle", "interception": "Interception",
        "pressure": "Pressure", "possession_change": "Change of possession", "out_of_play": "Ball out of play",
        "deflection": "Deflection", "kickoff": "Kick-off", "set_piece": "Set piece", "goal": "Goal"}
OUTCOME = {"success": "completed", "fail": "not completed", "on_target": "on target", "off_target": "off target",
           "blocked": "blocked", "goal": "a goal"}


def plain(f: dict) -> str:
    """One cited fact in plain words: when, what, who, and its values with their units."""
    parts = [f"{f.get('clock') or ''}".strip(), KIND.get(f.get("type"), f.get("type") or "Event")]
    who = f.get("player")
    if who:
        parts.append(f"by {who}")
    if f.get("team"):
        parts.append(f"({f['team']} team)")
    if f.get("receiver"):
        parts.append(f"to {f['receiver']}" if f.get("type") == "pass" else f"on {f['receiver']}")
    if f.get("interceptor"):
        parts.append(f"cut out by {f['interceptor']}")
    text = " ".join(p for p in parts if p)
    extra = []
    if f.get("outcome") in OUTCOME:
        extra.append(OUTCOME[f["outcome"]])
    if f.get("distance_m") is not None:
        extra.append(f"{f['distance_m']} m")
    if f.get("ball_speed_kmh") is not None:
        extra.append(f"ball at {f['ball_speed_kmh']} km/h")
    if f.get("minute") is not None:
        extra.append(f"match minute {f['minute']}")
    if f.get("confidence") is not None:
        extra.append(f"detected with confidence {f['confidence']:.2f}")
    if f.get("team_confidence") is not None:
        extra.append(f"its team told with confidence {f['team_confidence']:.2f}")
    return text + (": " + ", ".join(extra) if extra else "")


def pools(rows: list[dict]) -> dict[str, list[dict]]:
    run = [{"source": "factcheck_eval judge:4", "seed": r["seed"], "kind": r["kind"], "claim": r["claim"],
            "facts": r["evidence"], "verdict": verdict(r), "truth": r["true"]} for r in rows]
    return {
        "passed": [x for x, r in zip(run, rows, strict=True) if r["code_ok"] and r["judge_ok"]],
        "rejected by code": [x for x, r in zip(run, rows, strict=True) if not r["code_ok"]],
        "rejected by the Judge": [x for x, r in zip(run, rows, strict=True) if r["code_ok"] and r["judge_ok"] is False
                                  and r["category"] in ("unsupported_claim", "input")],
        "held": held(),
        "rewritten": rewritten(),
    }


def verdict(r: dict) -> str:
    if not r["code_ok"]:
        return "rejected (code)"
    return "passed" if r["judge_ok"] else f"rejected (Judge: {r['category']})"


def held() -> list[dict]:
    from ninety.agents.cues import _text
    from ninety.agents.factcheck import Claim, check, confidence_gate
    from ninety.match import detected
    from ninety.match.facts import compact
    from ninety.speech.describe import as_sentence

    out = []
    for seg in sorted(VISION.glob("*/joined/detected.jsonl")):
        events = detected.load(seg)
        known = {e["id"]: compact(e) for e in events}
        for e in events:
            if e["type"] not in ("pass", "shot"):
                continue
            claim = Claim(as_sentence(_text(e, "analyst") + "."), [e["id"]])
            if not check(claim, known).ok:
                continue
            v = confidence_gate(claim, known)
            if v.category == "low_confidence":
                out.append({"source": f"8080 dry run {seg.parent.parent.name}", "seed": 8080, "kind": e["type"],
                            "claim": claim.text, "facts": [{**known[e["id"]], "confidence": e["confidence"],
                                                            "team_confidence": e.get("team_confidence")}],
                            "verdict": "held (confidence gate)", "truth": None})
    return out


def rewritten() -> list[dict]:
    from ninety.agents import workflow
    from ninety.agents.replay import WorkflowRecording
    from ninety.match.facts import compact

    warnings.simplefilter("ignore")
    rec = WorkflowRecording.load(ROOT / "replays/workflow-minute2-plant.json")
    result = asyncio.run(workflow.replay_workflow(rec))
    by_id = {e["id"]: e for e in rec.inputs["events"]}
    out = []
    for s in result.trace:
        if s.action != "rewrite":
            continue
        m = re.match(r"^['\"](?P<text>.*)['\"](?: evidence=\[(?P<ev>[^\]]*)\])?\s*$", s.detail, re.S)
        if not m:
            raise SystemExit(f"unreadable rewrite step: {s.detail[:80]}")
        ids = re.findall(r"'([^']+)'", m["ev"] or "")
        if not ids:  # a rewrite citing the same evidence as its draft: the moment's
            moment = next(x for x in result.moments if x.id == s.moment)
            ids = list(moment.evidence)
        out.append({"source": "live workflow replay (seed 7, 2026-10-20)", "seed": 7, "kind": f"{s.role} rewrite",
                    "claim": m["text"], "facts": [compact(by_id[i]) for i in ids if i in by_id],
                    "verdict": "passed after a rewrite", "truth": None})
    return out


def main() -> None:
    rows = json.loads(Path(sys.argv[1]).read_text())
    rng = random.Random(SAMPLE_SEED)
    chosen = []
    for stratum, n in N.items():
        pool = sorted(pools(rows)[stratum], key=lambda x: (x["source"], x["seed"], x["kind"], x["claim"]))
        take = pool if len(pool) <= n else rng.sample(pool, n)
        chosen += [{**x, "stratum": stratum, "pool": len(pool)} for x in take]
    random.Random(ORDER_SEED).shuffle(chosen)
    items, key = [], {}
    for n, x in enumerate(chosen, 1):
        iid = f"L{n:02d}"
        facts = sorted(x["facts"], key=lambda f: (f.get("minute") or 0, f.get("clock") or ""))
        items.append({"id": iid, "sentence": x["claim"], "facts": [plain(f) for f in facts]})
        key[iid] = {k: x[k] for k in ("stratum", "verdict", "source", "seed", "kind", "truth", "pool")}
    (HERE / "items.json").write_text(json.dumps(items, indent=1, ensure_ascii=False) + "\n")
    (HERE / "key.json").write_text(json.dumps(key, indent=1, ensure_ascii=False) + "\n")
    (HERE / "index.html").write_text(page(items))
    print({s: sum(1 for v in key.values() if v["stratum"] == s) for s in N}, "items:", len(items))


def page(items: list[dict]) -> str:
    cards = "\n".join(f"""<article class="item" id="{i['id']}">
  <h2>{i['id']}</h2>
  <p class="sentence">&ldquo;{html.escape(i['sentence'])}&rdquo;</p>
  <h3>The cited facts</h3>
  <ul>{''.join(f'<li>{html.escape(f)}</li>' for f in i['facts'])}</ul>
  <fieldset><legend>Supported by the facts?</legend>
    {''.join(f'<label><input type="radio" name="{i["id"]}" value="{v}"> {v}</label>' for v in ("yes", "no", "unsure"))}
  </fieldset>
  <label class="note">Note (optional) <textarea data-note="{i['id']}" rows="2"></textarea></label>
</article>""" for i in items)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Fact-check labels</title>
<style>
:root {{ --bg:#fafaf7; --fg:#1d1d1b; --muted:#6b6b66; --card:#fff; --line:#e3e2dc; --accent:#1f6f4a; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#161614; --fg:#ecebe6; --muted:#a3a29b; --card:#1f1f1c; --line:#33332f; --accent:#5fc595; }} }}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--bg); color:var(--fg); font:16px/1.5 system-ui, sans-serif; }}
main {{ max-width:760px; margin:0 auto; padding:24px 16px 96px; }}
h1 {{ font-size:1.5rem; margin:0 0 4px; }}
.intro {{ color:var(--muted); }}
.item {{ background:var(--card); border:1px solid var(--line); border-radius:12px; padding:16px 18px; margin:16px 0; }}
.item h2 {{ font-size:.85rem; color:var(--muted); margin:0; letter-spacing:.04em; }}
.sentence {{ font-size:1.15rem; margin:8px 0 12px; }}
h3 {{ font-size:.85rem; margin:0; color:var(--muted); font-weight:600; }}
ul {{ margin:4px 0 12px; padding-left:20px; }}
fieldset {{ border:0; padding:0; margin:0 0 8px; display:flex; gap:18px; flex-wrap:wrap; }}
legend {{ font-weight:600; margin-bottom:6px; }}
label {{ cursor:pointer; }}
.note {{ display:block; color:var(--muted); font-size:.9rem; }}
textarea {{ width:100%; margin-top:4px; font:inherit; background:var(--bg); color:var(--fg); border:1px solid var(--line); border-radius:8px; padding:6px 8px; }}
.bar {{ position:fixed; left:0; right:0; bottom:0; background:var(--card); border-top:1px solid var(--line); padding:10px 16px; display:flex; gap:12px; align-items:center; justify-content:center; }}
button {{ font:inherit; background:var(--accent); color:#fff; border:0; border-radius:8px; padding:8px 16px; cursor:pointer; }}
#count {{ color:var(--muted); }}
</style></head>
<body><main>
<h1>Fact-check labels</h1>
<p class="intro">For each sentence, judge only from the facts listed under it: does everything the sentence says follow from them? Answer yes, no or unsure. You are not shown what our checker decided. Your answers save in this browser as you go; press Export at the end and send labels.json.</p>
{cards}
</main>
<div class="bar"><span id="count"></span><button id="export" type="button">Export labels.json</button></div>
<script>
const KEY = "ninety-factcheck-labels-v1";
const ids = {json.dumps([i["id"] for i in items])};
let saved = {{}};
try {{ saved = JSON.parse(localStorage.getItem(KEY) || "{{}}"); }} catch (e) {{ saved = {{}}; }}
function store() {{ try {{ localStorage.setItem(KEY, JSON.stringify(saved)); }} catch (e) {{}} count(); }}
function count() {{ const n = ids.filter(i => saved[i] && saved[i].answer).length; document.getElementById("count").textContent = n + " of " + ids.length + " answered"; }}
for (const id of ids) {{
  const s = saved[id] || {{}};
  for (const r of document.querySelectorAll(`input[name="${{id}}"]`)) {{
    if (r.value === s.answer) r.checked = true;
    r.addEventListener("change", () => {{ saved[id] = {{ ...(saved[id] || {{}}), answer: r.value }}; store(); }});
  }}
  const t = document.querySelector(`textarea[data-note="${{id}}"]`);
  t.value = s.note || "";
  t.addEventListener("input", () => {{ saved[id] = {{ ...(saved[id] || {{}}), note: t.value }}; store(); }});
}}
count();
document.getElementById("export").addEventListener("click", () => {{
  const body = JSON.stringify({{ format: 1, labelled_at: new Date().toISOString(), labels: saved }}, null, 1);
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([body], {{ type: "application/json" }}));
  a.download = "labels.json";
  a.click();
}});
</script></body></html>
"""


if __name__ == "__main__":
    main()
