"""Render parameters: everything that varies between clips, sampled from the seed.

Every value lands in `clip.json`, so any frame can be regenerated exactly. Knobs listed in
`PLANNED` are part of the contract but not drawn yet; setting them to a non-default value fails
loudly instead of silently rendering something the labels do not describe.

New random draws are appended after the original sequence, so a seed keeps the camera, kits and
lighting it already had. Weather and the camera cut are the exception: they are chosen at the end.
The tactical cameras' draws come last of all, so adding them moved nothing a seed already had.
"""

from __future__ import annotations

import colorsys
import random
from dataclasses import asdict, dataclass, field, fields, replace

LIGHTING = ("day", "dusk", "night", "overcast")
WEATHER = ("clear", "overcast", "rain")
OCCLUSION = ("natural", "crowded", "keeper")
# normal and low are drawn for training (low is a hard case); broadcast is set only for footage a
# viewer watches (the demo clip, docs/eval/demo-clip.md), never drawn from a seed.
KIT_CONTRAST = ("normal", "low", "broadcast")
# The stadium's dressing. plain is every training, validation and test render's look; broadcast (a crowd
# in the stands, hoardings and a surround all round, more varied boards, softer mowing) is set only for
# footage a viewer watches (the demo clip), never drawn from a seed, so no dataset changes look.
STADIUM = ("plain", "broadcast")
# The streams a clip writes besides the broadcast. none: the broadcast only. tactical: also the two
# fixed whole-pitch lenses on the gantry (camera.tactical_views), each written as a clip of its own
# under views/<name>/, from the same match and scene, frame for frame. Never drawn from a seed: it adds
# streams and leaves the broadcast byte-identical, so it is not an override of what a clip looks like.
VIEWS = ("none", "tactical")
# Shirt graphics. Colours stay fictional; a pattern is not a real club's kit.
PATTERNS = ("solid", "stripes", "hoops", "sash", "halves")

# Share of seeds drawn as each hard case (low-contrast kits; a crowded clip window), each on its
# own. Set from the train floors in ninety/vision/data_stats.py (each hard case in at least 20% of
# clips) before any clip was rendered at this rate: 150 clips at 0.3 average 45 of each, about
# 2.7 standard deviations above the floor of 30. Not tuned to any test-set number.
HARD_CASE_RATE = 0.3

# Knob -> the only values rendered for now. Dusk, night, overcast and rain are drawn by
# web/render but do not look like broadcast footage yet, so every clip is a clear day until they
# do; asking for one fails instead of putting a bad render into a dataset.
PLANNED: dict[str, tuple] = {"lighting": ("day",), "weather": ("clear",)}

# Fictional three-letter codes; none is a Premier League club code.
TEAM_CODES = ("ASH", "CRW", "DUN", "ELM", "FEN", "GRV", "HLT", "IVY", "KST", "MRL", "OAK", "QRY")
# The two teams every clip shows (Kian's decision, Oct 24): London Athletic at home, Lisbon Esportes
# away, both fictional. The seed still draws two TEAM_CODES, so every later draw of a seed (patterns,
# the camera cut, the tactical mount) stays where it was; the codes drawn are no longer shown.
TEAMS = {"home": ("LON", "London Athletic"), "away": ("LIS", "Lisbon Esportes")}
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
class TacticalParams:
    """Where the two fixed tactical lenses stand: side by side on the main gantry, both at one point.

    Aim and lens are solved from the position so each covers its half of the pitch
    (camera.tactical_views); only the mount is drawn. Defaults are the nominal mount: halfway, about
    1:1 height to distance back (docs/GROUNDING.md V7)."""

    height_m: float = 28.0  # above the pitch
    back_m: float = 32.0  # behind the near touchline
    offset_x_m: float = 0.0  # along the touchline from halfway


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
    # A broadcast clip cuts from a stoppage to its restart instead of showing the whole wait (edit.py).
    # Off here: datasets, the Azure job, training rounds and the test sets show every frame, since a
    # cut would thin the crowded and keeper windows unevenly and change what a test set measures.
    # `ninety-render` (viewer and demo clips) turns it on for every seed outside the test set.
    dead_ball_cut: bool = False
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
    # "crowded" picks the window where players most often hide the ball; "keeper" the one where a
    # goalkeeper most often handles or dives (override only: seeds never draw it)
    occlusion: str = "natural"
    home_code: str = TEAMS["home"][0]
    away_code: str = TEAMS["away"][0]
    boards: tuple[str, ...] = BOARD_BRANDS
    stadium: str = "plain"
    views: str = "none"
    tactical: TacticalParams = field(default_factory=TacticalParams)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["boards"] = list(self.boards)
        if self.stadium == "plain":
            # Absent means plain (web/render reads it so): a training clip's clip.json is what it was.
            del d["stadium"]
        if self.views == "none":
            # Absent means the broadcast only: a clip without views keeps the clip.json it had.
            del d["views"], d["tactical"]
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


def wcag_contrast(a: str, b: str) -> float:
    """WCAG 2.1 contrast ratio of two colours, 1..21, from their relative luminance (sRGB linearised)."""

    def rel(hex_: str) -> float:
        lin = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in _rgb(hex_)]
        return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]

    lo, hi = sorted((rel(a), rel(b)))
    return (hi + 0.05) / (lo + 0.05)


# Broadcast kits: WCAG 2.1 SC 1.4.11 asks 3:1 for graphical objects a viewer must tell apart; and two
# coloured shirts a third of the hue circle apart (*design*), so a team is not told by brightness alone.
BROADCAST_CONTRAST = 3.0
BROADCAST_HUE_DEG = 60.0


def _hue_apart(a: str, b: str) -> bool:
    (ha, sa, _), (hb, sb, _) = colorsys.rgb_to_hsv(*_rgb(a)), colorsys.rgb_to_hsv(*_rgb(b))
    if sa <= 0.1 or sb <= 0.1:  # white, black or grey: told apart by brightness
        return True
    gap = abs(ha - hb) * 360
    return min(gap, 360 - gap) >= BROADCAST_HUE_DEG


def kits_differ(a: str, b: str, contrast: str) -> bool:
    d, dl = color_distance(a, b), abs(luminance(a) - luminance(b))
    if contrast == "broadcast":
        return wcag_contrast(a, b) >= BROADCAST_CONTRAST and _hue_apart(a, b)
    if contrast == "low":
        return 0.15 <= d <= 0.35 and dl <= 0.08
    return d >= 0.55 and dl >= 0.12


# What a viewer sees of a shirt is its colour and its pattern's together. The page draws a pattern
# in the kit's trim, the shorts' colour unless the shorts match the shirt (web/render/render.js,
# `trim`), over this share of the shirt by the shader's own thresholds (render.js kitMaterial:
# stripes 0.42 of each period, hoops 0.46, halves one half, the sash a band 0.17 wide across a
# torso about 2 wide; the collar is ignored, as both teams have one).
PATTERN_SHARE = {"solid": 0.0, "stripes": 0.42, "hoops": 0.46, "sash": 0.085, "halves": 0.5}
NEUTRAL_TRIM = "#f2f2f2"  # render.js: the trim of a shirt whose shorts are its own colour


def _linear(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _gamma(c: float) -> float:
    return 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055


def visible_shirt(kit: Kit, pattern: str) -> str:
    """The shirt's colour as a camera a pitch away sees it: its colour and its pattern's mixed by
    area, in linear light (as the camera's pixels average them)."""
    trim = kit.shorts if kit.shorts.lower() != kit.shirt.lower() else NEUTRAL_TRIM
    share = PATTERN_SHARE[pattern]
    mixed = [(1 - share) * _linear(a) + share * _linear(b)
             for a, b in zip(_rgb(kit.shirt), _rgb(trim), strict=True)]
    return _hex([min(1.0, max(0.0, _gamma(c))) for c in mixed])


def kits_seen_apart(home: Kit, home_pattern: str, away: Kit, away_pattern: str) -> bool:
    """The broadcast test (kits_differ) on the shirts as seen, pattern included, not their base colours."""
    return kits_differ(visible_shirt(home, home_pattern), visible_shirt(away, away_pattern), "broadcast")


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
    # Lighting is still drawn, then set to day (see PLANNED), so every later draw of a seed and
    # hence its camera, kits and stadium stay where they were.
    drawn_lighting = rng.choice(LIGHTING)
    lighting = "day"
    elevation = {"day": rng.uniform(30, 60), "dusk": rng.uniform(8, 18), "night": 45.0, "overcast": 50.0}[
        lighting
    ]
    # Hard cases are drawn from the seed too, so the fixed test set (which refuses overrides) holds
    # them. Their own stream: a seed drawn normal and natural keeps every draw it had.
    hard = random.Random(f"render-hard-{seed}")
    drawn_contrast = "low" if hard.random() < HARD_CASE_RATE else "normal"
    drawn_occlusion = "crowded" if hard.random() < HARD_CASE_RATE else "natural"
    contrast = overrides.get("kit_contrast", drawn_contrast)
    home, away, hgk, agk = sample_kits(rng, contrast)
    rng.sample(TEAM_CODES, 2)  # drawn and not used, so later draws stay put (TEAMS)
    base = RenderParams(
        camera=cam,
        lighting=lighting,
        sun_azimuth_deg=round(rng.uniform(0, 360), 1),
        sun_elevation_deg=round(elevation, 1),
        weather="clear",
        kit_contrast=contrast,
        occlusion=drawn_occlusion,
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
        home_code=TEAMS["home"][0],
        away_code=TEAMS["away"][0],
    )
    # Appended draws. Everything above is the original sequence and must stay in this order.
    if drawn_lighting != "overcast":
        rng.random()  # the rain draw, kept so the camera cut and patterns stay where they were
    base = replace(
        base,
        home_pattern=rng.choice(PATTERNS),
        away_pattern=rng.choice(PATTERNS),
        camera_cut=rng.random() < 0.30,
    )
    if contrast == "broadcast":
        base = _kits_seen_apart(base, seed)
    # The tactical mount (*design* ranges round the nominal 28 m up, 32 m back, docs/GROUNDING.md V7),
    # drawn for every seed whether or not it writes the views, so a seed's mount never depends on it.
    base = replace(
        base,
        tactical=TacticalParams(
            height_m=round(rng.uniform(24, 32), 2),
            back_m=round(rng.uniform(28, 38), 2),
            offset_x_m=round(rng.uniform(-3, 3), 2),
        ),
    )
    return apply_overrides(base, overrides)


def _kits_seen_apart(p: RenderParams, seed: int) -> RenderParams:
    """Broadcast kits that pass on their base colours can still look alike once the pattern is on
    them (seed 8080: purple hoops in white over white shorts, against a white shirt). Redraw from
    their own stream until the shirts differ both as colours and as seen: the away kit first,
    keeping the home kit; if no away kit suits it, both. The keepers are redrawn with them. A seed
    that already passes keeps every draw, and only broadcast kits are tested."""
    if kits_seen_apart(p.home_kit, p.home_pattern, p.away_kit, p.away_pattern):
        return p
    fix = random.Random(f"render-kits-seen-{seed}")
    for attempt in range(20_000):
        home, away, hgk, agk = sample_kits(fix, "broadcast")
        home_pattern, away_pattern = fix.choice(PATTERNS), fix.choice(PATTERNS)
        if attempt < 2_000:  # keep the home kit while one away kit suits it
            home, home_pattern = p.home_kit, p.home_pattern
        if not (kits_differ(home.shirt, away.shirt, "broadcast")
                and kits_seen_apart(home, home_pattern, away, away_pattern)):
            continue
        seen = (visible_shirt(home, home_pattern), visible_shirt(away, away_pattern))
        if all(color_distance(k.shirt, o) >= 0.5 for k in (hgk, agk) for o in seen):
            return replace(p, home_kit=home, home_pattern=home_pattern, away_kit=away,
                           away_pattern=away_pattern, home_gk=hgk, away_gk=agk)
    raise RuntimeError("could not draw kits that look apart")  # pragma: no cover


def apply_overrides(p: RenderParams, overrides: dict) -> RenderParams:
    nested = {
        "camera": {f.name for f in fields(CameraParams)},
        "tactical": {f.name for f in fields(TacticalParams)},
    }
    top_fields = {f.name for f in fields(RenderParams)}
    sub_kw: dict[str, dict] = {name: {} for name in nested}
    top_kw = {}
    for k, v in overrides.items():
        group, _, key = k.partition(".")
        if group in nested and key in nested[group]:
            sub_kw[group][key] = v
        elif k in top_fields and k not in nested:
            top_kw[k] = v
        else:
            raise ValueError(f"unknown render parameter: {k}")
    for group, kw in sub_kw.items():
        if kw:
            top_kw[group] = replace(getattr(p, group), **kw)
    p = replace(p, **top_kw)
    validate(p)
    return p


def validate(p: RenderParams) -> None:
    for name, allowed in (
        ("lighting", LIGHTING),
        ("weather", WEATHER),
        ("occlusion", OCCLUSION),
        ("kit_contrast", KIT_CONTRAST),
        ("stadium", STADIUM),
        ("views", VIEWS),
    ):
        if getattr(p, name) not in allowed:
            raise ValueError(f"{name} must be one of {allowed}, got {getattr(p, name)!r}")
    for name in ("home_pattern", "away_pattern"):
        if getattr(p, name) not in PATTERNS:
            raise ValueError(f"{name} must be one of {PATTERNS}, got {getattr(p, name)!r}")
    for name in ("camera_cut", "dead_ball_cut"):
        if not isinstance(getattr(p, name), bool):
            raise ValueError(f"{name} must be true or false")
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
