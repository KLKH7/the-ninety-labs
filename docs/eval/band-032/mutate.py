"""The mutation run for the per-look band (docs/eval/band-032-plan.md): each mutant must fail a test.

    uv run python docs/eval/band-032/mutate.py
"""
import subprocess
from pathlib import Path

OBS, DER = "ninety/vision/observe.py", "ninety/eval/band_derive.py"
B032 = "BAND_032 = (0.901, 0.994)"
M = [
    (OBS, B032, "BAND_032 = (0.966, 1.121)", "0.3.2 band = main's"),
    (OBS, B032, "BAND_032 = (0.91, 0.994)", "0.3.2 band low end moved"),
    (OBS, B032, "BAND_032 = (0.901, 1.002)", "0.3.2 band = old band"),
    (OBS, 'DEFAULT_LOOK = "0.5.15"', 'DEFAULT_LOOK = "0.3.2"', "default look is 0.3.2"),
    (OBS, "ok = band[0] <= ratio <= band[1] and",
     "ok = HEIGHT_BAND[0] <= ratio <= HEIGHT_BAND[1] and", "place ignores band"),
    (OBS, "rows.append(place(x, markings=not fixed, band=band))",
     "rows.append(place(x, markings=not fixed))", "regate ignores look"),
    (OBS, "        if band != HEIGHT_BAND:  # judged", "        if False:  # judged",
     "fit path ignores look"),
    (OBS, "choices=sorted(BANDS), default", "default", "any look accepted"),
    (OBS, '(cam["markings_ok"] or not markings)', "True", "B3 markings dropped"),
    (DER, "if len(looks - {None}) > 1:", "if False:", "mixed looks allowed"),
    (DER, '"renderer": look[0] if look else None}', '"renderer": None}', "renderer not recorded"),
]
TESTS = ["tests/test_vision_observe.py", "tests/test_vision_observe_band_looks.py",
         "tests/test_band_derive.py"]

for f, a, b, name in M:
    p = Path(f)
    s = p.read_text()
    assert s.count(a) == 1, (name, s.count(a))
    p.write_text(s.replace(a, b))
    try:
        r = subprocess.run(["uv", "run", "pytest", "-q", "-x", *TESTS], capture_output=True, text=True)
    finally:
        p.write_text(s)
    print(("KILLED  " if r.returncode else "SURVIVED"), name, flush=True)
