import subprocess, sys
from pathlib import Path
M = [
 ("ninety/vision/observe.py", "BAND_032 = (0.901, 0.994)", "BAND_032 = (0.966, 1.121)", "0.3.2 band = main's"),
 ("ninety/vision/observe.py", "BAND_032 = (0.901, 0.994)", "BAND_032 = (0.91, 0.994)", "0.3.2 band low end moved"),
 ("ninety/vision/observe.py", "BAND_032 = (0.901, 0.994)", "BAND_032 = (0.901, 1.002)", "0.3.2 band = old band"),
 ("ninety/vision/observe.py", 'DEFAULT_LOOK = "0.5.15"', 'DEFAULT_LOOK = "0.3.2"', "default look is 0.3.2"),
 ("ninety/vision/observe.py", "ok = band[0] <= ratio <= band[1] and", "ok = HEIGHT_BAND[0] <= ratio <= HEIGHT_BAND[1] and", "place ignores band"),
 ("ninety/vision/observe.py", "rows.append(place(x, markings=not fixed, band=band))", "rows.append(place(x, markings=not fixed))", "regate ignores look"),
 ("ninety/vision/observe.py", "        if band != HEIGHT_BAND:  # judged", "        if False:  # judged", "fit path ignores look"),
 ("ninety/vision/observe.py", "choices=sorted(BANDS), default", "default", "any look accepted"),
 ("ninety/vision/observe.py", "(cam[\"markings_ok\"] or not markings)", "True", "B3 markings dropped"),
 ("ninety/eval/band_derive.py", "if len(looks - {None}) > 1:", "if False:", "mixed looks allowed"),
 ("ninety/eval/band_derive.py", 'return {"seeds": seeds, "renderer": look[0] if look else None}', 'return {"seeds": seeds, "renderer": None}', "renderer not recorded"),
]
tests = ["tests/test_vision_observe.py", "tests/test_vision_observe_band_looks.py", "tests/test_band_derive.py"]
for f, a, b, name in M:
    p = Path(f); s = p.read_text()
    assert s.count(a) == 1, (name, s.count(a))
    p.write_text(s.replace(a, b))
    try:
        r = subprocess.run(["uv", "run", "pytest", "-q", "-x", *tests], capture_output=True, text=True)
    finally:
        p.write_text(s)
    print(("KILLED  " if r.returncode else "SURVIVED"), name, flush=True)
