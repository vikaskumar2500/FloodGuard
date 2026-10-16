import re

from .models import OSMWay

DRIVABLE_HIGHWAYS = frozenset(
    {
        "motorway",
        "motorway_link",
        "trunk",
        "trunk_link",
        "primary",
        "primary_link",
        "secondary",
        "secondary_link",
        "tertiary",
        "tertiary_link",
        "residential",
        "living_street",
        "service",
        "unclassified",
    }
)

DEFAULT_SPEED_KPH: dict[str, float] = {
    "motorway": 100,
    "motorway_link": 60,
    "trunk": 80,
    "trunk_link": 50,
    "primary": 60,
    "primary_link": 50,
    "secondary": 50,
    "secondary_link": 40,
    "tertiary": 40,
    "tertiary_link": 35,
    "residential": 30,
    "living_street": 10,
    "service": 20,
    "unclassified": 30,
}

_SPEED_PATTERN = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(mph|mi/h|km/?h)?\s*$", re.IGNORECASE)


def is_drivable(way: OSMWay) -> bool:
    highway = way.tags.get("highway", "").lower()
    if highway not in DRIVABLE_HIGHWAYS:
        return False
    return not any(
        way.tags.get(tag, "").lower() in {"no", "private", "agricultural", "forestry"}
        for tag in ("access", "motor_vehicle", "motorcar", "vehicle")
    )


def is_access_restricted(way: OSMWay) -> bool:
    return way.tags.get("highway", "").lower() in DRIVABLE_HIGHWAYS and not is_drivable(way)


def parse_oneway(way: OSMWay) -> int:
    value = way.tags.get("oneway", "").lower()
    if value in {"-1", "reverse"}:
        return -1
    if value in {"yes", "1", "true"}:
        return 1
    if value == "no":
        return 0
    if way.tags.get("junction", "").lower() == "roundabout":
        return 1
    return 0


def speed_limit_kph(way: OSMWay) -> tuple[float, bool]:
    road_class = way.tags.get("highway", "unclassified").lower()
    fallback = DEFAULT_SPEED_KPH.get(road_class, DEFAULT_SPEED_KPH["unclassified"])
    raw = way.tags.get("maxspeed", "")
    if not raw:
        return fallback, False
    match = _SPEED_PATTERN.match(raw.split(";")[0])
    if not match:
        return fallback, True
    value = float(match.group(1))
    if value <= 0:
        return fallback, True
    if match.group(2) and match.group(2).lower() in {"mph", "mi/h"}:
        value *= 1.609344
    return value, False


def metadata_for(way: OSMWay) -> dict[str, str]:
    keys = ("name", "ref", "surface", "bridge", "tunnel", "junction", "maxspeed")
    return {key: way.tags[key] for key in keys if key in way.tags}
