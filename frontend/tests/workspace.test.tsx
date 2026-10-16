import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { FloodGuardWorkspace } from "@/components/floodguard-workspace";
import type { FloodMapProps } from "@/components/map/flood-map";
import { healthyReport } from "./health-fixture";

vi.mock("@/components/map/map-shell", () => ({
  MapShell: (props: FloodMapProps) => (
    <div aria-label="Interactive route map">
      <button
        type="button"
        onClick={() =>
          props.onMapSelect({ latitude: 19.076, longitude: 72.8777 })
        }
      >
        Map click
      </button>
      <button
        type="button"
        onClick={() => props.onMapError("The map style failed.")}
      >
        Map error
      </button>
      <span>Source marker: {props.source ? "visible" : "hidden"}</span>
      <span>
        Destination marker: {props.destination ? "visible" : "hidden"}
      </span>
      <span>Route layer: {props.route ? "visible" : "hidden"}</span>
    </div>
  ),
}));

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function renderWorkspace() {
  vi.stubGlobal(
    "fetch",
    vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input).includes("/routes/calculate")) {
        const body = JSON.parse(String(init?.body)) as {
          source: { latitude: number; longitude: number };
          destination: { latitude: number; longitude: number };
        };
        if (
          body.source.latitude === body.destination.latitude &&
          body.source.longitude === body.destination.longitude
        ) {
          return Promise.resolve({
            ok: false,
            status: 422,
            json: async () => ({
              detail: "Source and destination must differ.",
            }),
          });
        }
        return Promise.resolve({
          ok: true,
          status: 201,
          json: async () => ({
            routeId: "route-test",
            graphVersionId: "graph-test",
            algorithm: "ASTAR",
            mode: body.destination ? "SAFEST" : "BALANCED",
            distanceMeters: 2000,
            estimatedTimeSeconds: 300,
            riskScore: null,
            riskLevel: "LOW",
            riskConfidence: 0,
            maxEdgeRisk: 0,
            highRiskDistanceMeters: 0,
            expandedNodes: 4,
            riskModelActive: false,
            riskSegments: [],
            geometry: {
              type: "LineString",
              coordinates: [
                [72.8777, 19.076],
                [72.89, 19.09],
              ],
            },
          }),
        });
      }
      return Promise.resolve({ status: 200, json: async () => healthyReport });
    }),
  );
  render(<FloodGuardWorkspace />);
}

function setLocation(
  label: "Source" | "Destination",
  latitude: string,
  longitude: string,
) {
  fireEvent.change(screen.getByLabelText(`${label} latitude`), {
    target: { value: latitude },
  });
  fireEvent.change(screen.getByLabelText(`${label} longitude`), {
    target: { value: longitude },
  });
  fireEvent.click(
    screen.getByRole("button", {
      name: `Set ${label.toLowerCase()} coordinates`,
    }),
  );
}

test("calculate remains disabled until source and destination are valid", () => {
  renderWorkspace();
  const calculate = screen.getByRole("button", {
    name: "Calculate route",
  });
  expect(calculate).toBeDisabled();
  setLocation("Source", "19.076", "72.8777");
  expect(screen.getByText("Source marker: visible")).toBeInTheDocument();
  expect(calculate).toBeDisabled();
  setLocation("Destination", "19.09", "72.89");
  expect(screen.getByText("Destination marker: visible")).toBeInTheDocument();
  expect(calculate).toBeEnabled();
});

test("map clicks select source then destination", () => {
  renderWorkspace();
  const mapClick = screen.getByRole("button", { name: "Map click" });
  fireEvent.click(mapClick);
  expect(screen.getByText("Source marker: visible")).toBeInTheDocument();
  fireEvent.click(mapClick);
  expect(screen.getByText("Destination marker: visible")).toBeInTheDocument();
});

test("mode switching calculates summary and clear removes route", async () => {
  renderWorkspace();
  setLocation("Source", "19.076", "72.8777");
  setLocation("Destination", "19.09", "72.89");
  fireEvent.click(screen.getByLabelText("Safest"));
  fireEvent.click(screen.getByRole("button", { name: "Calculate route" }));
  expect(
    await screen.findByRole("heading", { name: "Route summary" }),
  ).toBeInTheDocument();
  expect(screen.getByText("SAFEST")).toBeInTheDocument();
  expect(screen.getByText("Route layer: visible")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Clear route" }));
  expect(
    screen.queryByRole("heading", { name: "Route summary" }),
  ).not.toBeInTheDocument();
  expect(screen.getByText("Route layer: hidden")).toBeInTheDocument();
});

test("invalid coordinate input shows a useful error", () => {
  renderWorkspace();
  setLocation("Source", "91", "72");
  expect(screen.getByRole("alert")).toHaveTextContent("latitude −90 to 90");
});

test("map errors and route failures are user friendly", async () => {
  renderWorkspace();
  fireEvent.click(screen.getByRole("button", { name: "Map error" }));
  expect(screen.getByRole("alert")).toHaveTextContent("map style failed");
  setLocation("Source", "19.076", "72.8777");
  setLocation("Destination", "19.076", "72.8777");
  fireEvent.click(screen.getByRole("button", { name: "Calculate route" }));
  await waitFor(() =>
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Source and destination must differ",
    ),
  );
});

test("geolocation is requested on click and permission denial is handled", async () => {
  const getCurrentPosition = vi.fn((_success, failure: PositionErrorCallback) =>
    failure({
      code: 1,
      message: "denied",
      PERMISSION_DENIED: 1,
      POSITION_UNAVAILABLE: 2,
      TIMEOUT: 3,
    }),
  );
  vi.stubGlobal("navigator", {
    ...navigator,
    geolocation: { getCurrentPosition },
  });
  renderWorkspace();
  expect(getCurrentPosition).not.toHaveBeenCalled();
  fireEvent.click(
    screen.getByRole("button", { name: "Use my location as source" }),
  );
  await waitFor(() =>
    expect(screen.getByRole("alert")).toHaveTextContent(
      "permission was denied",
    ),
  );
  expect(getCurrentPosition).toHaveBeenCalledTimes(1);
});

test("reset all removes both locations and route", async () => {
  renderWorkspace();
  setLocation("Source", "19.076", "72.8777");
  setLocation("Destination", "19.09", "72.89");
  fireEvent.click(screen.getByRole("button", { name: "Calculate route" }));
  await screen.findByRole("heading", { name: "Route summary" });
  fireEvent.click(screen.getByRole("button", { name: "Reset all" }));
  expect(screen.getByText("Source marker: hidden")).toBeInTheDocument();
  expect(screen.getByText("Destination marker: hidden")).toBeInTheDocument();
  expect(screen.getByText("Route layer: hidden")).toBeInTheDocument();
});
