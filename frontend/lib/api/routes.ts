import type { GeoPoint, GeoJsonPosition } from "@/lib/geo/coordinates";
import { isValidGeoPoint } from "@/lib/geo/coordinates";
import { apiBaseUrl, apiPrefix } from "@/lib/health";

export const routeModes = ["FASTEST", "BALANCED", "SAFEST"] as const;
export type RouteMode = (typeof routeModes)[number];

export type RouteRequest = Readonly<{
  source: GeoPoint;
  destination: GeoPoint;
  mode: RouteMode;
  algorithm?: RouteAlgorithm;
}>;

export type RouteAlgorithm = "DIJKSTRA" | "ASTAR";

export type RouteLineString = Readonly<{
  type: "LineString";
  coordinates: readonly GeoJsonPosition[];
}>;

export type MLRouteMetadata = Readonly<{
  mode: "DISABLED" | "SHADOW" | "ACTIVE";
  available: boolean;
  modelVersion: string;
  predictionHorizonMinutes?: number;
  provenanceWarning?: string;
}>;

export type RouteResponse = Readonly<{
  routeId: string;
  graphVersionId: string;
  geometry: RouteLineString;
  distanceMeters: number;
  estimatedTimeSeconds: number;
  riskScore: number | null;
  riskLevel: "LOW" | "MODERATE" | "HIGH" | "SEVERE";
  riskConfidence: number;
  maxEdgeRisk: number;
  highRiskDistanceMeters: number;
  expandedNodes: number;
  riskModelActive: boolean;
  riskSegments: readonly RiskSegment[];
  algorithm: RouteAlgorithm;
  mode: RouteMode;
  ml?: MLRouteMetadata | null;
}>;

export type RiskSegment = Readonly<{
  edgeId: string;
  riskScore: number;
  riskLevel: "LOW" | "MODERATE" | "HIGH" | "SEVERE";
  confidence: number;
  explanation: string;
  geometry: RouteLineString;
  mlProbability?: number | null;
  deterministicRisk?: number | null;
  fusedRisk?: number | null;
}>;

function isRouteResponse(value: unknown): value is RouteResponse {
  if (typeof value !== "object" || value === null) return false;
  const route = value as Record<string, unknown>;
  const geometry = route.geometry as Record<string, unknown> | undefined;
  return (
    typeof route.routeId === "string" &&
    typeof route.graphVersionId === "string" &&
    typeof route.distanceMeters === "number" &&
    typeof route.estimatedTimeSeconds === "number" &&
    (route.riskScore === null || typeof route.riskScore === "number") &&
    ["LOW", "MODERATE", "HIGH", "SEVERE"].includes(String(route.riskLevel)) &&
    typeof route.riskConfidence === "number" &&
    typeof route.maxEdgeRisk === "number" &&
    typeof route.highRiskDistanceMeters === "number" &&
    typeof route.expandedNodes === "number" &&
    typeof route.riskModelActive === "boolean" &&
    Array.isArray(route.riskSegments) &&
    (route.algorithm === "DIJKSTRA" || route.algorithm === "ASTAR") &&
    (route.mode === "FASTEST" ||
      route.mode === "BALANCED" ||
      route.mode === "SAFEST") &&
    geometry?.type === "LineString" &&
    Array.isArray(geometry.coordinates)
  );
}

export async function calculateRoute(
  request: RouteRequest,
): Promise<RouteResponse> {
  if (
    !isValidGeoPoint(request.source) ||
    !isValidGeoPoint(request.destination)
  ) {
    throw new RangeError("Choose valid source and destination coordinates.");
  }
  const response = await fetch(`${apiBaseUrl}${apiPrefix}/routes/calculate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      source: request.source,
      destination: request.destination,
      mode: request.mode,
      algorithm: request.algorithm ?? "ASTAR",
    }),
  });
  const body: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const detail =
      typeof body === "object" && body !== null && "detail" in body
        ? String((body as { detail: unknown }).detail)
        : "The routing service rejected the request.";
    throw new Error(detail);
  }
  if (!isRouteResponse(body))
    throw new Error("The routing service returned an invalid response.");
  return body;
}
