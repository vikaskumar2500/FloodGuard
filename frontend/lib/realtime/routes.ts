import { apiBaseUrl, apiPrefix } from "@/lib/health";
import type { RiskSegment, RouteLineString, RouteMode } from "@/lib/api/routes";

export type RouteEventType =
  | "route.created"
  | "route.risk_updated"
  | "route.invalidated"
  | "route.rerouting"
  | "route.recalculated"
  | "route.reroute_failed"
  | "heartbeat";

export type RouteEvent = Readonly<{
  eventId: string;
  eventType: RouteEventType;
  routeId: string;
  sequence: number;
  occurredAt: string;
  riskRevision: number;
  data: Record<string, unknown>;
}>;

export type RecalculatedData = Readonly<{
  oldRouteId: string;
  newRouteId: string;
  reason: string;
  mode: RouteMode;
  algorithm: "ASTAR" | "DIJKSTRA";
  oldRiskScore: number;
  newRiskScore: number;
  oldRiskLevel: "LOW" | "MODERATE" | "HIGH" | "SEVERE";
  newRiskLevel: "LOW" | "MODERATE" | "HIGH" | "SEVERE";
  oldRiskConfidence: number;
  newRiskConfidence: number;
  oldEtaSeconds: number;
  newEtaSeconds: number;
  etaDeltaSeconds: number;
  riskReduction: number;
  distanceMeters: number;
  geometry: RouteLineString;
  riskSegments: readonly RiskSegment[];
  graphVersionId: string;
  riskRevision: number;
}>;

export type RouteStreamHandlers = Readonly<{
  onEvent: (event: RouteEvent) => void;
  onReconnecting: () => void;
}>;

export type RouteSubscription = Readonly<{ close: () => void }>;

export function subscribeToRoute(
  routeId: string,
  handlers: RouteStreamHandlers,
): RouteSubscription {
  const source = new EventSource(
    `${apiBaseUrl}${apiPrefix}/routes/${routeId}/events`,
  );
  const receive = (message: MessageEvent<string>) => {
    try {
      handlers.onEvent(JSON.parse(message.data) as RouteEvent);
    } catch {
      handlers.onReconnecting();
    }
  };
  for (const type of [
    "route.created",
    "route.risk_updated",
    "route.invalidated",
    "route.rerouting",
    "route.recalculated",
    "route.reroute_failed",
    "heartbeat",
  ])
    source.addEventListener(type, receive as EventListener);
  source.onerror = handlers.onReconnecting;
  return { close: () => source.close() };
}
