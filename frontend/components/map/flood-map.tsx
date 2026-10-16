"use client";

import { useEffect, useRef, useState } from "react";
import maplibregl, {
  type GeoJSONSource,
  type Map as MapLibreMap,
  type Marker,
} from "maplibre-gl";
import type { RouteResponse } from "@/lib/api/routes";
import type { GeoPoint } from "@/lib/geo/coordinates";
import {
  createLocationMarkerElement,
  markerCoordinates,
} from "./location-marker";
import {
  initialViewport,
  mapStyleUrl,
  riskColors,
  routeLayerId,
  routeSourceId,
  previousRouteLayerId,
  previousRouteSourceId,
} from "./map-style";
import { RiskLegend } from "./risk-legend";

type SelectionMode = "source" | "destination";

export type FloodMapProps = Readonly<{
  source: GeoPoint | null;
  destination: GeoPoint | null;
  route: RouteResponse | null;
  previousRoute: RouteResponse | null;
  selectionMode: SelectionMode;
  onMapSelect: (point: GeoPoint) => void;
  onMapError: (message: string) => void;
}>;

const emptyRoute: GeoJSON.FeatureCollection<GeoJSON.LineString> = {
  type: "FeatureCollection",
  features: [],
};

function routeFeature(
  route: RouteResponse | null,
): GeoJSON.FeatureCollection<GeoJSON.LineString> {
  if (!route) return emptyRoute;
  const features = route.riskSegments.length
    ? route.riskSegments.map((segment) => ({
        type: "Feature" as const,
        properties: { riskLevel: segment.riskLevel },
        geometry: {
          type: "LineString" as const,
          coordinates: segment.geometry.coordinates.map(
            ([longitude, latitude]) => [longitude, latitude],
          ),
        },
      }))
    : [
        {
          type: "Feature" as const,
          properties: { riskLevel: route.riskLevel },
          geometry: {
            type: "LineString" as const,
            coordinates: route.geometry.coordinates.map(
              ([longitude, latitude]) => [longitude, latitude],
            ),
          },
        },
      ];
  return { type: "FeatureCollection", features };
}

export default function FloodMap({
  source,
  destination,
  route,
  previousRoute,
  selectionMode,
  onMapSelect,
  onMapError,
}: FloodMapProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const sourceMarkerRef = useRef<Marker | null>(null);
  const destinationMarkerRef = useRef<Marker | null>(null);
  const clickHandlerRef = useRef(onMapSelect);
  const errorHandlerRef = useRef(onMapError);
  const [ready, setReady] = useState(false);
  const [resourceWarning, setResourceWarning] = useState(false);

  useEffect(() => {
    clickHandlerRef.current = onMapSelect;
    errorHandlerRef.current = onMapError;
  }, [onMapSelect, onMapError]);

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;
    let map: MapLibreMap;
    try {
      map = new maplibregl.Map({
        container: containerRef.current,
        style: mapStyleUrl,
        center: initialViewport.center,
        zoom: initialViewport.zoom,
        attributionControl: {},
      });
      mapRef.current = map;
      map.addControl(
        new maplibregl.NavigationControl({ showCompass: false }),
        "top-right",
      );

      map.on("load", () => {
        map.addSource(routeSourceId, { type: "geojson", data: emptyRoute });
        map.addSource(previousRouteSourceId, {
          type: "geojson",
          data: emptyRoute,
        });
        map.addLayer({
          id: previousRouteLayerId,
          type: "line",
          source: previousRouteSourceId,
          layout: { "line-cap": "round", "line-join": "round" },
          paint: {
            "line-color": "#64748b",
            "line-width": 5,
            "line-opacity": 0.65,
            "line-dasharray": [2, 2],
          },
        });
        map.addLayer({
          id: routeLayerId,
          type: "line",
          source: routeSourceId,
          layout: { "line-cap": "round", "line-join": "round" },
          paint: {
            "line-color": [
              "match",
              ["get", "riskLevel"],
              "LOW",
              riskColors.LOW,
              "MODERATE",
              riskColors.MODERATE,
              "HIGH",
              riskColors.HIGH,
              "SEVERE",
              riskColors.SEVERE,
              riskColors.MODERATE,
            ],
            "line-width": ["interpolate", ["linear"], ["zoom"], 8, 4, 16, 8],
            "line-opacity": 0.92,
          },
        });
        setReady(true);
      });
      map.on("click", (event) => {
        clickHandlerRef.current({
          latitude: event.lngLat.lat,
          longitude: event.lngLat.lng,
        });
      });
      map.on("error", () => {
        setResourceWarning(true);
        errorHandlerRef.current(
          "The map style or tiles could not be loaded completely.",
        );
      });
    } catch {
      errorHandlerRef.current("The interactive map could not be initialized.");
      return;
    }

    return () => {
      sourceMarkerRef.current?.remove();
      destinationMarkerRef.current?.remove();
      sourceMarkerRef.current = null;
      destinationMarkerRef.current = null;
      mapRef.current = null;
      map.remove();
    };
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    const data = routeFeature(route);
    (map.getSource(routeSourceId) as GeoJSONSource | undefined)?.setData(data);
    if (route && route.geometry.coordinates.length > 1) {
      const bounds = route.geometry.coordinates.reduce(
        (result, coordinate) => result.extend([coordinate[0], coordinate[1]]),
        new maplibregl.LngLatBounds(),
      );
      map.fitBounds(bounds, { padding: 72, maxZoom: 15, duration: 500 });
    }
  }, [ready, route]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    (
      map.getSource(previousRouteSourceId) as GeoJSONSource | undefined
    )?.setData(routeFeature(previousRoute));
  }, [previousRoute, ready]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    sourceMarkerRef.current?.remove();
    sourceMarkerRef.current = source
      ? new maplibregl.Marker({
          element: createLocationMarkerElement("source"),
        })
          .setLngLat(markerCoordinates(source))
          .addTo(map)
      : null;
  }, [source]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    destinationMarkerRef.current?.remove();
    destinationMarkerRef.current = destination
      ? new maplibregl.Marker({
          element: createLocationMarkerElement("destination"),
        })
          .setLngLat(markerCoordinates(destination))
          .addTo(map)
      : null;
  }, [destination]);

  function resetView() {
    const map = mapRef.current;
    if (!map) return;
    if (route && route.geometry.coordinates.length > 1) {
      const bounds = route.geometry.coordinates.reduce(
        (result, coordinate) => result.extend([coordinate[0], coordinate[1]]),
        new maplibregl.LngLatBounds(),
      );
      map.fitBounds(bounds, { padding: 72, maxZoom: 15 });
    } else {
      map.flyTo(initialViewport);
    }
  }

  return (
    <section
      className="relative h-full min-h-[420px] overflow-hidden bg-slate-200"
      aria-label="Interactive route map"
    >
      <div
        ref={containerRef}
        className="absolute inset-0 w-full h-full"
        style={{ position: "absolute", top: 0, left: 0, right: 0, bottom: 0, width: "100%", height: "100%" }}
        data-testid="map-container"
      />
      {!ready && (
        <div
          className="absolute inset-0 z-20 grid place-items-center bg-slate-100 text-sm text-slate-600"
          role="status"
        >
          Loading interactive map…
        </div>
      )}
      <div className="map-card absolute top-3 left-3 z-10 max-w-[min(19rem,calc(100%-6rem))] text-xs text-slate-700">
        <span className="font-semibold">Map selection:</span> click to set{" "}
        {selectionMode === "source" ? "the source" : "the destination"}.
      </div>
      <button
        type="button"
        onClick={resetView}
        className="map-action absolute top-24 right-3 z-10"
        aria-label="Reset map view"
      >
        Fit route
      </button>
      {resourceWarning && (
        <p
          className="map-card absolute top-14 left-3 z-10 max-w-xs text-xs text-red-800"
          role="alert"
        >
          Some map resources are unavailable. Coordinate controls still work.
        </p>
      )}
      <RiskLegend />
    </section>
  );
}
