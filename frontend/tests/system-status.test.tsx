import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { StatusCard } from "@/components/status-card";
import { SystemStatus } from "@/components/system-status";
import { healthyReport } from "./health-fixture";

afterEach(() => vi.unstubAllGlobals());

test("status card displays healthy state", () => {
  render(<StatusCard name="API" status="healthy" description="Connected" />);
  expect(screen.getByText("Healthy")).toBeInTheDocument();
});

test("status card displays unavailable state", () => {
  render(
    <StatusCard name="API" status="unavailable" description="Not connected" />,
  );
  expect(screen.getByText("Unavailable")).toBeInTheDocument();
});

test("dashboard displays live healthy dependency results", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({ status: 200, json: async () => healthyReport }),
  );
  render(<SystemStatus />);
  await screen.findByText("All required services are connected.");
  expect(
    within(
      screen.getByRole("article", { name: "PostgreSQL status" }),
    ).getByText("Healthy"),
  ).toBeInTheDocument();
  expect(screen.getAllByText("Healthy")).toHaveLength(3);
});

test("readiness 503 keeps responding API healthy and shows Redis unavailable", async () => {
  const report = {
    ...healthyReport,
    status: "degraded",
    ready: false,
    dependencies: {
      ...healthyReport.dependencies,
      redis: { status: "unavailable", message: "Redis unavailable" },
    },
  };
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({ status: 503, json: async () => report }),
  );
  render(<SystemStatus />);
  await screen.findByText(
    "The API is responding, but the system is not ready.",
  );
  expect(
    within(screen.getByRole("article", { name: "API status" })).getByText(
      "Healthy",
    ),
  ).toBeInTheDocument();
  expect(
    within(screen.getByRole("article", { name: "Redis status" })).getByText(
      "Unavailable",
    ),
  ).toBeInTheDocument();
});

test("missing PostGIS displays PostgreSQL degraded state", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      status: 503,
      json: async () => ({
        ...healthyReport,
        status: "unavailable",
        ready: false,
        dependencies: {
          ...healthyReport.dependencies,
          postgis: { status: "unavailable", message: "PostGIS unavailable" },
        },
      }),
    }),
  );
  render(<SystemStatus />);
  await screen.findByText(
    "The API is responding, but the system is not ready.",
  );
  expect(
    within(
      screen.getByRole("article", { name: "PostgreSQL status" }),
    ).getByText("Degraded"),
  ).toBeInTheDocument();
});

test("API outage shows unavailable and refresh recovers", async () => {
  const fetch = vi
    .fn()
    .mockRejectedValueOnce(new Error("Network unavailable"))
    .mockResolvedValue({ status: 200, json: async () => healthyReport });
  vi.stubGlobal("fetch", fetch);
  render(<SystemStatus />);
  await screen.findByText(
    "Unable to reach the API. Check the backend and try again.",
  );
  expect(screen.getAllByText("Unavailable")).toHaveLength(3);
  fireEvent.click(screen.getByRole("button", { name: "Refresh status" }));
  await screen.findByText("All required services are connected.");
  expect(fetch).toHaveBeenCalledTimes(2);
});

test("malformed API response does not claim healthy status", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      status: 200,
      json: async () => ({ status: "healthy" }),
    }),
  );
  render(<SystemStatus />);
  await screen.findByText(
    "Unable to reach the API. Check the backend and try again.",
  );
  expect(screen.getAllByText("Unavailable")).toHaveLength(3);
});
