import { expect, test, vi } from "vitest";
import { calculateRoute } from "@/lib/api/routes";

const source = { latitude: 19.076, longitude: 72.8777 };
const destination = { latitude: 19.09, longitude: 72.89 };

const backendRoute = {
  routeId: "route-1",
  graphVersionId: "graph-1",
  algorithm: "ASTAR" as const,
  mode: "SAFEST" as const,
  distanceMeters: 7421.5,
  estimatedTimeSeconds: 962.1,
  riskScore: null,
  riskLevel: "LOW" as const,
  riskConfidence: 0,
  maxEdgeRisk: 0,
  highRiskDistanceMeters: 0,
  expandedNodes: 12,
  riskModelActive: false,
  riskSegments: [],
  geometry: {
    type: "LineString" as const,
    coordinates: [
      [72.8777, 19.076],
      [72.89, 19.09],
    ] as [number, number][],
  },
};

test("route service sends the request to the backend API", async () => {
  const fetchMock = vi.fn().mockResolvedValue({
    ok: true,
    json: async () => backendRoute,
  });
  vi.stubGlobal("fetch", fetchMock);

  const result = await calculateRoute({ source, destination, mode: "SAFEST" });

  expect(result).toEqual(backendRoute);
  expect(fetchMock).toHaveBeenCalledWith(
    expect.stringContaining("/routes/calculate"),
    expect.objectContaining({ method: "POST" }),
  );
});

test("backend route response remains GeoJSON-compatible", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({ ok: true, json: async () => backendRoute }),
  );
  const first = await calculateRoute({ source, destination, mode: "SAFEST" });
  const second = await calculateRoute({ source, destination, mode: "SAFEST" });
  expect(first).toEqual(second);
  expect(first.algorithm).toBe("ASTAR");
  expect(first.geometry.type).toBe("LineString");
  expect(first.geometry.coordinates).toHaveLength(2);
  expect(first.geometry.coordinates[0]).toEqual([72.8777, 19.076]);
  expect(first.geometry.coordinates[1]).toEqual([72.89, 19.09]);
});

test("route service rejects invalid points before making a request", async () => {
  await expect(
    calculateRoute({
      source: { latitude: 100, longitude: 0 },
      destination,
      mode: "FASTEST",
    }),
  ).rejects.toThrow("valid source");
});
