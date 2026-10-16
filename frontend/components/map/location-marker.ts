import type { GeoPoint } from "@/lib/geo/coordinates";

export type LocationKind = "source" | "destination";

export function createLocationMarkerElement(
  kind: LocationKind,
): HTMLDivElement {
  const element = document.createElement("div");
  element.className = `location-marker location-marker--${kind}`;
  element.setAttribute("role", "img");
  element.setAttribute(
    "aria-label",
    kind === "source" ? "Source marker" : "Destination marker",
  );
  element.textContent = kind === "source" ? "S" : "D";
  return element;
}

export function markerCoordinates(point: GeoPoint): [number, number] {
  return [point.longitude, point.latitude];
}
