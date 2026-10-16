import { describe, expect, test } from "vitest";
import {
  initialRouteState,
  routeLifecycleReducer,
} from "@/lib/realtime/route-lifecycle";
import type { RouteResponse } from "@/lib/api/routes";
import type { RouteEvent } from "@/lib/realtime/routes";

const route: RouteResponse = {
  routeId: "11111111-1111-4111-8111-111111111111",
  graphVersionId: "graph-1",
  algorithm: "ASTAR",
  mode: "SAFEST",
  distanceMeters: 300,
  estimatedTimeSeconds: 180,
  riskScore: 0.2,
  riskLevel: "LOW",
  riskConfidence: 0.9,
  maxEdgeRisk: 0.2,
  highRiskDistanceMeters: 0,
  expandedNodes: 4,
  riskModelActive: true,
  riskSegments: [],
  geometry: {
    type: "LineString",
    coordinates: [
      [0, 0],
      [3, 0],
    ],
  },
};

function event(
  eventType: RouteEvent["eventType"],
  sequence: number,
  data: Record<string, unknown> = {},
): RouteEvent {
  return {
    eventId: `${sequence}`,
    eventType,
    routeId: route.routeId,
    sequence,
    occurredAt: new Date(0).toISOString(),
    riskRevision: 1,
    data,
  };
}

describe("route lifecycle", () => {
  test("ignores duplicate and stale sequences", () => {
    let state = routeLifecycleReducer(initialRouteState, {
      type: "CALCULATED",
      route,
    });
    state = routeLifecycleReducer(state, {
      type: "EVENT",
      event: event("route.invalidated", 4),
    });
    const accepted = state;
    state = routeLifecycleReducer(state, {
      type: "EVENT",
      event: event("route.rerouting", 4),
    });
    state = routeLifecycleReducer(state, {
      type: "EVENT",
      event: event("route.rerouting", 3),
    });
    expect(state).toEqual(accepted);
    state = routeLifecycleReducer(state, {
      type: "EVENT",
      event: event("route.rerouting", 5),
    });
    expect(state.lifecycle).toBe("REROUTING");
  });

  test("retains old route and installs replacement geometry and comparison", () => {
    let state = routeLifecycleReducer(initialRouteState, {
      type: "CALCULATED",
      route,
    });
    state = routeLifecycleReducer(state, {
      type: "EVENT",
      event: event("route.recalculated", 3, {
        oldRouteId: route.routeId,
        newRouteId: "22222222-2222-4222-8222-222222222222",
        reason: "route_unsafe",
        mode: "SAFEST",
        algorithm: "ASTAR",
        oldRiskScore: 0.8,
        newRiskScore: 0.15,
        oldRiskLevel: "SEVERE",
        newRiskLevel: "LOW",
        oldRiskConfidence: 0.9,
        newRiskConfidence: 0.8,
        oldEtaSeconds: 180,
        newEtaSeconds: 210,
        etaDeltaSeconds: 30,
        riskReduction: 0.65,
        distanceMeters: 600,
        geometry: {
          type: "LineString",
          coordinates: [
            [0, 0],
            [0, 1],
            [3, 0],
          ],
        },
        riskSegments: [],
        graphVersionId: "graph-1",
        riskRevision: 1,
      }),
    });
    expect(state.lifecycle).toBe("REROUTED");
    expect(state.previousRoute?.routeId).toBe(route.routeId);
    expect(state.route?.routeId).toBe("22222222-2222-4222-8222-222222222222");
    expect(state.comparison?.riskReduction).toBe(0.65);
  });
});
