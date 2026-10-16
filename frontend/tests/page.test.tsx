import { render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import Home from "@/app/page";
import { healthyReport } from "./health-fixture";

vi.mock("@/components/map/map-shell", () => ({
  MapShell: () => <div aria-label="Interactive route map">Mock map</div>,
}));

afterEach(() => vi.unstubAllGlobals());

test("main page renders FloodGuard and the project tagline", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({ status: 200, json: async () => healthyReport }),
  );
  render(<Home />);
  expect(screen.getByText("FloodGuard")).toBeInTheDocument();
  expect(
    screen.getByText("Real-Time Flood Intelligence & Safe Routing"),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("heading", { name: "Plan a journey" }),
  ).toBeInTheDocument();
  expect(screen.getByLabelText("Interactive route map")).toBeInTheDocument();
  expect(
    await screen.findByLabelText("Open system status"),
  ).toBeInTheDocument();
});
