"""Render parameters: everything that varies between clips, sampled from the seed.

Every value lands in `clip.json`, so any frame can be regenerated exactly. Knobs listed in
`PLANNED` are part of the contract but not drawn yet; setting them to a non-default value fails
loudly instead of silently rendering something the labels do not describe.

New random draws are appended after the original sequence, so a seed keeps the camera, kits and
lighting it already had. Weather and the camera cut are the exception: they are chosen at the end.
"""

from __future__ import annotations

import colorsys
import random
from dataclasses import asdict, dataclass, field, fields, replace

LIGHTING = ("day", "dusk", "night", "overcast")
WEATHER = ("clear", "overcast", "rain")
OCCLUSION = ("natural", "crowded")
KIT_CONTRAST = ("normal", "low")
# Shirt graphics. Colours stay fictional; a pattern is not a real club's kit.
PATTERNS = ("solid", "stripes", "hoops", "sash", "halves")

# Knob -> values that are accepted but not drawn. Empty: rain and camera cuts are built.
PLANNED: dict[str, tuple] = {}

# Fictional three-letter codes; none is a Premier League club code.
TEAM_CODES = ("ASH", "CRW", "DUN", "ELM", "FEN", "GRV", "HLT", "IVY", "KST", "MRL", "OAK", "QRY")
# Made-up advertising brands for the pitch-side boards.
BOARD_BRANDS = ("VANTIRO", "QELMORA", "BRISKEL", "OSTRAVEN", "PALMIRU", "ZENTHA", "THE NINETY LABS")


@dataclass(frozen=True)
class CameraParams:
    height_m: float = 20.0  # gantry height above the pitch
    back_m: float = 35.0  # distance behind the near touchline
    offset_x_m: float = 0.0  # along the touchline from halfway
    half_width_m: float = 20.0  # half the ground width kept in shot in open play
    box_half_width_m: float = 14.0  # tighter framing when the ball is in a penalty box
    pan_lag_s: float = 0.6  # time constant of the follow filter
    lead_s: float = 0.35  # aim ahead of the ball by its velocity times this
    shake_m: float = 0.08  # amplitude of handheld-style aim jitter


@dataclass(frozen=True)
class Kit:
    shirt: str
    shorts: str
    socks: str


@dataclass(frozen=True)
class RenderParams:
    width: int = 1280
    height: int = 720
    fps: int = 25
    camera: CameraParams = field(default_factory=CameraParams)
    lighting: str = "day"
    sun_azimuth_deg: float = 210.0
    sun_elevation_deg: float = 40.0
    weather: str = "clear"
    camera_cut: bool = False
    kit_contrast: str = "normal"
    home_kit: Kit = Kit("#c8102e", "#ffffff", "#c8102e")
    away_kit: Kit = Kit("#1d4ed8", "#1d4ed8", "#ffffff")
    home_gk: Kit = Kit("#16a34a", "#111111", "#16a34a")
    away_gk: Kit = Kit("#eab308", "#111111", "#eab308")
    home_pattern: str = "solid"
    away_pattern: str = "solid"
    grass_hue: float = 0.28  # HSV hue of the turf
    stripe_width_m: float = 5.25
    wear: float = 0.5  # 0 pristine, 1 heavily worn goalmouths and centre
    stand_color: str = "#3a3f4a"
    crowd_density: float = 0.8
    motion_blur: float = 0.5  # shutter as a fraction of the frame interval
    noise: float = 0.012  # sensor noise amplitude, linear 0..1
    jpeg_quality: float = 0.88
    occlusion: str = "natural"  # "crowded" picks the clip window with most players near the ball
    home_code: str = "ASH"
    away_code: str = "CRW"
    boards: tuple[str, ...] = BOARD_BRANDS

    def to_dict(self) -> dict:
        d = asdict(self)
        d["boards"] = list(self.boards)
        return d


def _hex(rgb: tuple[float, float, float]) -> str:
    return "#" + "".join(f"{round(c * 255):02x}" for c in rgb)


def _rgb(hex_: str) -> tuple[float, float, float]:
    h = hex_.lstrip("#")
    return tuple(int(h[i : i + 2], 16) / 255 for i in (0, 2, 4))  # type: ignore[return-value]


def luminance(hex_: str) -> float:
    r, g, b = _rgb(hex_)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def color_distance(a: str, b: str) -> float:
    """Euclidean distance in RGB, 0..sqrt(3)."""
    return sum((x - y) ** 2 for x, y in zip(_rgb(a), _rgb(b), strict=True)) ** 0.5


def _random_color(rng: random.Random) -> str:
    h = rng.random()
    s = rng.choice((0.0, rng.uniform(0.55, 0.95)))
    v = rng.uniform(0.12, 0.95) if s else rng.choice((0.1, 0.95))
    return _hex(colorsys.hsv_to_rgb(h, s, v))


def kits_differ(a: str, b: str, contrast: str) -> bool:
    d, dl = color_distance(a, b), abs(luminance(a) - luminance(b))
    if contrast == "low":
        return 0.15 <= d <= 0.35 and dl <= 0.08
    return d >= 0.55 and dl >= 0.12


def sample_kits(rng: random.Random, contrast: str) -> tuple[Kit, Kit, Kit, Kit]:
    for _ in range(10_000):
        home, away = _random_color(rng), _random_color(rng)
        if kits_differ(home, away, contrast):
            break
    else:  # pragma: no cover - the colour space is large enough
        raise RuntimeError("could not sample kits")
    grass = "#3f7a2a"
    gk = []
    for _ in range(2):
        for _ in range(10_000):
            c = _random_color(rng)
            if all(color_distance(c, o) >= 0.5 for o in (home, away, grass, *gk)):
                gk.append(c)
                break

    def kit(c: str) -> Kit:
        second = rng.choice(("#ffffff", "#111111", c))
        return Kit(c, second, rng.choice((c, second)))

    return kit(home), kit(away), kit(gk[0]), kit(gk[1])


def sample_params(seed: int, **overrides) -> RenderParams:
    """Draw every randomized choice for a clip from its seed, then apply explicit overrides."""
    rng = random.Random(f"render-{seed}")
    cam = CameraParams(
        height_m=round(rng.uniform(15, 25), 2),
        back_m=round(rng.uniform(30, 40), 2),
        offset_x_m=round(rng.uniform(-6, 6), 2),
        half_width_m=round(rng.uniform(17, 24), 2),
        box_half_width_m=round(rng.uniform(11, 15), 2),
        pan_lag_s=round(rng.uniform(0.4, 0.9), 2),
        lead_s=round(rng.uniform(0.2, 0.5), 2),
        shake_m=round(rng.uniform(0.0, 0.15), 3),
    )
    lighting = rng.choice(LIGHTING)
    elevation = {"day": rng.uniform(30, 60), "dusk": rng.uniform(8, 18), "night": 45.0, "overcast": 50.0}[
        lighting
    ]
    contrast = overrides.get("kit_contrast", "normal")
    home, away, hgk, agk = sample_kits(rng, contrast)
    codes = rng.sample(TEAM_CODES, 2)
    base = RenderParams(
        camera=cam,
        lighting=lighting,
        sun_azimuth_deg=round(rng.uniform(0, 360), 1),
        sun_elevation_deg=round(elevation, 1),
        weather="overcast" if lighting == "overcast" else "clear",
        kit_contrast=contrast,
        home_kit=home,
        away_kit=away,
        home_gk=hgk,
        away_gk=agk,
        grass_hue=round(rng.uniform(0.24, 0.32), 3),
        stripe_width_m=rng.choice((4.0, 5.0, 5.25, 6.0)),
        wear=round(rng.uniform(0.1, 0.9), 2),
        stand_color=_hex(colorsys.hsv_to_rgb(rng.random(), rng.uniform(0.0, 0.5), rng.uniform(0.15, 0.4))),
        crowd_density=round(rng.uniform(0.5, 1.0), 2),
        motion_blur=round(rng.uniform(0.3, 0.7), 2),
        noise=round(rng.uniform(0.006, 0.02), 4),
        home_code=codes[0],
        away_code=codes[1],
    )
    # Appended draws. Everything above is the original sequence and must stay in this order.
    weather = base.weather
    if weather == "clear" and rng.random() < 0.34:
        weather = "rain"
    base = replace(
        base,
        home_pattern=rng.choice(PATTERNS),
        away_pattern=rng.choice(PATTERNS),
        camera_cut=rng.random() < 0.30,
        weather=weather,
    )
    return apply_overrides(base, overrides)


def apply_overrides(p: RenderParams, overrides: dict) -> RenderParams:
    cam_fields = {f.name for f in fields(CameraParams)}
    top_fields = {f.name for f in fields(RenderParams)}
    cam_kw, top_kw = {}, {}
    for k, v in overrides.items():
        key = k.removeprefix("camera.")
        if k.startswith("camera.") and key in cam_fields:
            cam_kw[key] = v
        elif k in top_fields and k != "camera":
            top_kw[k] = v
        else:
            raise ValueError(f"unknown render parameter: {k}")
    if cam_kw:
        top_kw["camera"] = replace(p.camera, **cam_kw)
    p = replace(p, **top_kw)
    validate(p)
    return p


def validate(p: RenderParams) -> None:
    for name, allowed in (
        ("lighting", LIGHTING),
        ("weather", WEATHER),
        ("occlusion", OCCLUSION),
        ("kit_contrast", KIT_CONTRAST),
    ):
        if getattr(p, name) not in allowed:
            raise ValueError(f"{name} must be one of {allowed}, got {getattr(p, name)!r}")
    for name in ("home_pattern", "away_pattern"):
        if getattr(p, name) not in PATTERNS:
            raise ValueError(f"{name} must be one of {PATTERNS}, got {getattr(p, name)!r}")
    if not isinstance(p.camera_cut, bool):
        raise ValueError("camera_cut must be true or false")
    for name, ok in PLANNED.items():
        if getattr(p, name) not in ok:
            raise NotImplementedError(f"render parameter {name}={getattr(p, name)!r} is planned, not built")
    if not 0 <= p.motion_blur <= 1:
        raise ValueError("motion_blur is a shutter fraction in 0..1")


def parse_override(text: str) -> tuple[str, object]:
    """Parse a CLI `--set key=value` into a typed override."""
    if "=" not in text:
        raise ValueError(f"expected key=value, got {text!r}")
    key, raw = text.split("=", 1)
    value: object = raw
    if raw.lower() in ("true", "false"):
        value = raw.lower() == "true"
    else:
        try:
            value = int(raw)
        except ValueError:
            try:
                value = float(raw)
            except ValueError:
                value = raw
    return key.strip(), value
