import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { EnvironmentStatus } from "@/components/environment-status";

describe("EnvironmentStatus", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders weather observation when fetch succeeds", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({
          provider: "open_meteo",
          latitude: 19.076,
          longitude: 72.8777,
          observed_at: "2026-10-08T12:00:00Z",
          rainfall_mm_per_hour: 8.5,
          temperature_c: 28.0,
          humidity_percent: 75.0,
          wind_speed_mps: 3.5,
          source_quality: "good",
          data_source_state: "LIVE",
          freshness: "FRESH",
        }),
      }),
    );

    render(<EnvironmentStatus />);

    await waitFor(() => {
      expect(screen.getByTestId("environment-status")).toBeInTheDocument();
    });

    expect(screen.getByText(/🌧️ 8.5 mm\/h/)).toBeInTheDocument();
    expect(screen.getByText(/28°C/)).toBeInTheDocument();
    expect(screen.getByText("FRESH")).toBeInTheDocument();
  });

  it("handles fetch failure gracefully", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new Error("Network error")),
    );

    render(<EnvironmentStatus />);

    await waitFor(() => {
      expect(screen.getByText(/Weather: offline/)).toBeInTheDocument();
    });
  });
});
