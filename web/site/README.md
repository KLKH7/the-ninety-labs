# web/site: the project page

The hackathon's project page ([BRIEF.md](../../docs/BRIEF.md#submission-checklist)): what The Ninety
Labs is, the five stages with what runs today, the measured results, the architecture, the
Microsoft stack and how to run it. One static HTML file and one stylesheet; no build step, no
scripts, no web fonts, no trackers. Deploying it is the M2 deploy's job, not this folder's.

Open it locally:

```bash
python3 -m http.server 8765 --directory web/site    # then http://127.0.0.1:8765
```

## Rules

- **Describe only what runs** ([AGENTS.md](../../AGENTS.md), honest claims). Each stage card and
  each row of the stack table has a status: `running`, `running locally`, `in progress` or
  `planned`. When something ships, change its status in the same pull request as
  [CHALLENGE_MAP.md](../../docs/CHALLENGE_MAP.md).
- **Every number comes from a report.** Write it as
  `<data value="0.994" data-src="docs/eval/vision-report-v2.json" data-key="by_class.player.recall" data-fmt="3">0.994</data>`,
  with a link to the report (its `.json` or `.md`) in the same paragraph, list item or table.
  `data-key` is a dotted path into the JSON (`a.tp+fn` adds two fields); for
  `fact-checker.json` it names a count computed in `tests/test_site.py`. `data-fmt` is `int` or
  the number of decimals. A digit anywhere else in the prose fails the tests; dates go in `<time>`
  and commands in `<code>`.
- **Links** go to files on `main` (`https://github.com/KLKH7/the-ninety-labs/blob/main/<path>`,
  or `tree/main/` for a folder), to ids on the page, or to files in this folder. Nothing else.
- **Synthetic only.** Stills come from our renderer; no real clubs, players, crests or footage.

`tests/test_site.py` checks all of this, plus alt text, landmarks and colour contrast (WCAG AA
for every text colour on every background in `site.css`).

## The still

`stills/` holds one frame from our renderer and an SVG of its ground-truth boxes, laid over it on
the page. To remake them (one render process, about four minutes on a laptop):

```bash
uv run ninety-render --seed 7 --seconds 2 --gpu --out runs/site-still
uv run python web/site/stills.py runs/site-still --frame 1970
```

[`stills/provenance.json`](stills/provenance.json) records the command, the renderer version and
the commit.
