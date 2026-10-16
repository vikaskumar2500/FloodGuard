from collections.abc import Iterator
from pathlib import Path
from xml.etree import ElementTree

from .models import OSMNode, OSMWay


def parse_osm_xml(path: Path) -> tuple[dict[int, OSMNode], list[OSMWay], tuple[float, ...] | None]:
    if not path.is_file():
        raise FileNotFoundError(f"OSM source file does not exist: {path}")
    if path.suffix.lower() != ".osm":
        raise ValueError("Phase 4 currently supports uncompressed .osm XML extracts")

    nodes: dict[int, OSMNode] = {}
    ways: list[OSMWay] = []
    bounds: tuple[float, ...] | None = None
    try:
        events: Iterator[tuple[str, ElementTree.Element]] = ElementTree.iterparse(
            path, events=("start", "end")
        )
        for event, element in events:
            if event == "start" and element.tag == "bounds":
                bounds = (
                    float(element.attrib["minlon"]),
                    float(element.attrib["minlat"]),
                    float(element.attrib["maxlon"]),
                    float(element.attrib["maxlat"]),
                )
            if event != "end":
                continue
            if element.tag == "node":
                try:
                    node_id = int(element.attrib["id"])
                    latitude = float(element.attrib["lat"])
                    longitude = float(element.attrib["lon"])
                except (KeyError, TypeError, ValueError) as error:
                    raise ValueError("OSM node is missing a valid id/lat/lon") from error
                if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
                    raise ValueError(f"OSM node {node_id} has invalid coordinates")
                nodes[node_id] = OSMNode(node_id, longitude, latitude)
            elif element.tag == "way":
                try:
                    way_id = int(element.attrib["id"])
                except (KeyError, ValueError) as error:
                    raise ValueError("OSM way is missing a valid id") from error
                node_ids = tuple(
                    int(child.attrib["ref"])
                    for child in element
                    if child.tag == "nd" and "ref" in child.attrib
                )
                tags = {
                    child.attrib["k"]: child.attrib["v"]
                    for child in element
                    if child.tag == "tag" and "k" in child.attrib and "v" in child.attrib
                }
                ways.append(OSMWay(way_id, node_ids, tags))
            if element.tag in {"node", "way", "bounds"}:
                element.clear()
    except ElementTree.ParseError as error:
        raise ValueError(f"Invalid OSM XML source: {path}") from error
    return nodes, ways, bounds
