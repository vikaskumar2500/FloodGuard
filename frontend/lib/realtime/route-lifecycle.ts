import type { RouteResponse } from "@/lib/api/routes";
import type { RecalculatedData, RouteEvent } from "./routes";

export type RouteLifecycle =
  | "IDLE"
  | "CALCULATING"
  | "ACTIVE"
  | "RISK_UPDATED"
  | "INVALIDATED"
  | "REROUTING"
  | "REROUTED"
  | "REROUTE_FAILED"
  | "STREAM_RECONNECTING"
  | "ERROR";

export type RouteState = Readonly<{
  lifecycle: RouteLifecycle;
  route: RouteResponse | null;
  previousRoute: RouteResponse | null;
  comparison: RecalculatedData | null;
  lastSequence: number;
  message: string;
}>;

export type RouteAction =
  | { type: "CALCULATING" }
  | { type: "CALCULATED"; route: RouteResponse }
  | { type: "EVENT"; event: RouteEvent }
  | { type: "RECONNECTING" }
  | { type: "ERROR"; message: string }
  | { type: "CLEAR" }
  | { type: "DISMISS_COMPARISON" };

export const initialRouteState: RouteState = {
  lifecycle: "IDLE",
  route: null,
  previousRoute: null,
  comparison: null,
  lastSequence: 0,
  message: "",
};

export function routeLifecycleReducer(
  state: RouteState,
  action: RouteAction,
): RouteState {
  if (action.type === "CLEAR") return initialRouteState;
  if (action.type === "CALCULATING")
    return { ...state, lifecycle: "CALCULATING", message: "" };
  if (action.type === "CALCULATED")
    return { ...initialRouteState, lifecycle: "ACTIVE", route: action.route };
  if (action.type === "RECONNECTING")
    return {
      ...state,
      lifecycle: "STREAM_RECONNECTING",
      message: "Reconnecting to live updates…",
    };
  if (action.type === "ERROR")
    return { ...state, lifecycle: "ERROR", message: action.message };
  if (action.type === "DISMISS_COMPARISON")
    return { ...state, previousRoute: null, comparison: null };
  const event = action.event;
  if (event.eventType === "heartbeat") return state;
  if (event.sequence <= state.lastSequence) return state;
  const base = { ...state, lastSequence: event.sequence };
  if (event.eventType === "route.invalidated")
    return {
      ...base,
      lifecycle: "INVALIDATED",
      message: "Current route affected by flood conditions.",
    };
  if (event.eventType === "route.rerouting")
    return {
      ...base,
      lifecycle: "REROUTING",
      message: "Finding a safer route…",
    };
  if (event.eventType === "route.reroute_failed")
    return {
      ...base,
      lifecycle: "REROUTE_FAILED",
      message: "No safer alternative found.",
    };
  if (event.eventType === "route.risk_updated" && state.route) {
    const data = event.data;
    return {
      ...base,
      lifecycle: "RISK_UPDATED",
      message: "Flood risk updated",
      route: {
        ...state.route,
        riskScore: Number(data.riskScore),
        riskLevel: data.riskLevel as RouteResponse["riskLevel"],
        riskConfidence: Number(data.riskConfidence),
        riskSegments: (data.riskSegments ??
          state.route.riskSegments) as RouteResponse["riskSegments"],
      },
    };
  }
  if (event.eventType === "route.recalculated" && state.route) {
    const data = event.data as RecalculatedData;
    const replacement: RouteResponse = {
      ...state.route,
      routeId: data.newRouteId,
      graphVersionId: data.graphVersionId,
      mode: data.mode,
      algorithm: data.algorithm,
      distanceMeters: data.distanceMeters,
      estimatedTimeSeconds: data.newEtaSeconds,
      riskScore: data.newRiskScore,
      riskLevel: data.newRiskLevel,
      riskConfidence: data.newRiskConfidence,
      geometry: data.geometry,
      riskSegments: data.riskSegments,
    };
    return {
      ...base,
      lifecycle: "REROUTED",
      route: replacement,
      previousRoute: state.route,
      comparison: data,
      lastSequence: 0,
      message: "Route updated due to flood risk",
    };
  }
  return base;
}
