import type { RouteMode } from "@/lib/api/routes";

export const mapStyleUrl = process.env.NEXT_PUBLIC_MAP_STYLE_URL || "https://basemaps.cartocdn.com/gl/voyager-gl-style/style.json";

export const initialViewport = {
  center: [76.65, 9.50] as [number, number],
  zoom: 9,
};

export const routeColors: Record<RouteMode, string> = {
  FASTEST: "#2563eb",
  BALANCED: "#0f766e",
  SAFEST: "#7c3aed",
};

export const riskColors = {
  LOW: "#0f766e",
  MODERATE: "#d97706",
  HIGH: "#ea580c",
  SEVERE: "#b91c1c",
} as const;

export const routeSourceId = "mock-route";
export const routeLayerId = "mock-route-line";
export const previousRouteSourceId = "previous-route";
export const previousRouteLayerId = "previous-route-line";
