import { render, screen, waitFor } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import FloodMap from "@/components/map/flood-map";

const remove = vi.fn();
const setData = vi.fn();
const addSource = vi.fn();
const addLayer = vi.fn();
const fitBounds = vi.fn();

vi.mock("maplibre-gl", () => {
  class MapMock {
    addControl = vi.fn();
    addSource = addSource;
    addLayer = addLayer;
    getSource = vi.fn(() => ({ setData }));
    setPaintProperty = vi.fn();
    fitBounds = fitBounds;
    flyTo = vi.fn();
    remove = remove;
    on(event: string, callback: (value: unknown) => void) {
      if (event === "load") queueMicrotask(() => callback({}));
      return this;
    }
  }
  class MarkerMock {
    setLngLat() {
      return this;
    }
    addTo() {
      return this;
    }
    remove() {
      return this;
    }
  }
  class BoundsMock {
    extend() {
      return this;
    }
  }
  return {
    default: {
      Map: MapMock,
      Marker: MarkerMock,
      NavigationControl: class {},
      LngLatBounds: BoundsMock,
    },
  };
});

test("map creates one GeoJSON source, updates the route, fits bounds, and cleans up", async () => {
  const { unmount } = render(
    <FloodMap
      source={{ latitude: 19.076, longitude: 72.8777 }}
      destination={{ latitude: 19.09, longitude: 72.89 }}
      selectionMode="destination"
      onMapSelect={vi.fn()}
      onMapError={vi.fn()}
      previousRoute={null}
      route={{
        routeId: "mock-test",
        geometry: {
          type: "LineString",
          coordinates: [
            [72.8777, 19.076],
            [72.89, 19.09],
          ],
        },
        distanceMeters: 2000,
        estimatedTimeSeconds: 300,
        riskScore: null,
        riskLevel: "LOW",
        riskConfidence: 0,
        maxEdgeRisk: 0,
        highRiskDistanceMeters: 0,
        expandedNodes: 2,
        riskModelActive: false,
        riskSegments: [],
        graphVersionId: "graph-test",
        algorithm: "ASTAR",
        mode: "SAFEST",
      }}
    />,
  );
  expect(screen.getByTestId("map-container")).toBeInTheDocument();
  await waitFor(() => expect(addSource).toHaveBeenCalledTimes(2));
  await waitFor(() => expect(setData).toHaveBeenCalled());
  expect(addLayer).toHaveBeenCalledTimes(2);
  expect(fitBounds).toHaveBeenCalled();
  unmount();
  expect(remove).toHaveBeenCalledTimes(1);
});
