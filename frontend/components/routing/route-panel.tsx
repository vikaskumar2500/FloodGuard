"use client";

import type { RouteMode, RouteResponse } from "@/lib/api/routes";
import { routeModes } from "@/lib/api/routes";
import type { GeoPoint } from "@/lib/geo/coordinates";
import { LocationSelector } from "./location-selector";
import { RouteSummary } from "./route-summary";
import type { RouteLifecycle } from "@/lib/realtime/route-lifecycle";
import type { RecalculatedData } from "@/lib/realtime/routes";

export function RoutePanel({
  source,
  destination,
  mode,
  route,
  selectionMode,
  loading,
  error,
  lifecycle,
  lifecycleMessage,
  comparison,
  onDismissComparison,
  onSourceChange,
  onDestinationChange,
  onModeChange,
  onSelectionModeChange,
  onCalculate,
  onClearRoute,
  onReset,
  onUseLocation,
}: Readonly<{
  source: GeoPoint | null;
  destination: GeoPoint | null;
  mode: RouteMode;
  route: RouteResponse | null;
  selectionMode: "source" | "destination";
  loading: boolean;
  error: string;
  lifecycle: RouteLifecycle;
  lifecycleMessage: string;
  comparison: RecalculatedData | null;
  onDismissComparison: () => void;
  onSourceChange: (point: GeoPoint | null) => void;
  onDestinationChange: (point: GeoPoint | null) => void;
  onModeChange: (mode: RouteMode) => void;
  onSelectionModeChange: (mode: "source" | "destination") => void;
  onCalculate: () => void;
  onClearRoute: () => void;
  onReset: () => void;
  onUseLocation: () => void;
}>) {
  return (
    <aside className="route-panel" aria-labelledby="route-planner-title">
      <div>
        <p className="text-[11px] font-semibold tracking-[0.18em] text-teal-700 uppercase">
          Route preview
        </p>
        <h1
          id="route-planner-title"
          className="mt-1 text-2xl font-semibold tracking-tight"
        >
          Plan a journey
        </h1>
        <p className="mt-2 text-xs leading-5 text-slate-500">
          Choose points on the map or enter coordinates. Flood risk is not
          active yet.
        </p>
      </div>

      <div className="mt-5 grid gap-3">
        <LocationSelector
          key={`source-${source?.latitude ?? "empty"}-${source?.longitude ?? "empty"}`}
          label="Source"
          point={source}
          active={selectionMode === "source"}
          onActivate={() => onSelectionModeChange("source")}
          onChange={(point) => onSourceChange(point)}
          onClear={() => onSourceChange(null)}
        />
        <button
          type="button"
          onClick={onUseLocation}
          className="w-full rounded-lg border border-teal-700 px-3 py-2.5 text-sm font-semibold text-teal-800 hover:bg-teal-50"
        >
          Use my location as source
        </button>
        <LocationSelector
          key={`destination-${destination?.latitude ?? "empty"}-${destination?.longitude ?? "empty"}`}
          label="Destination"
          point={destination}
          active={selectionMode === "destination"}
          onActivate={() => onSelectionModeChange("destination")}
          onChange={(point) => onDestinationChange(point)}
          onClear={() => onDestinationChange(null)}
        />
      </div>

      <fieldset className="mt-5">
        <legend className="text-sm font-semibold text-slate-900">
          Routing mode
        </legend>
        <div className="mt-2 grid grid-cols-3 gap-1 rounded-xl bg-slate-100 p-1">
          {routeModes.map((value) => (
            <label
              key={value}
              className={`route-mode ${mode === value ? "route-mode--selected" : ""}`}
            >
              <input
                type="radio"
                name="route-mode"
                value={value}
                checked={mode === value}
                onChange={() => onModeChange(value)}
                className="sr-only"
              />
              {value[0] + value.slice(1).toLowerCase()}
            </label>
          ))}
        </div>
      </fieldset>

      {error && (
        <p
          className="mt-4 rounded-lg bg-red-50 p-3 text-xs leading-5 text-red-800"
          role="alert"
        >
          {error}
        </p>
      )}

      {lifecycleMessage && (
        <p
          className={`mt-4 rounded-lg p-3 text-xs font-semibold ${
            lifecycle === "INVALIDATED" || lifecycle === "REROUTE_FAILED"
              ? "bg-red-50 text-red-800"
              : "bg-amber-50 text-amber-900"
          }`}
          role="status"
        >
          {lifecycleMessage}
        </p>
      )}

      <div className="mt-5 grid grid-cols-2 gap-2">
        <button
          type="button"
          disabled={!source || !destination || loading}
          onClick={onCalculate}
          className="col-span-2 rounded-xl bg-teal-800 px-4 py-3 text-sm font-semibold text-white shadow-sm hover:bg-teal-900 disabled:cursor-not-allowed disabled:bg-slate-300"
        >
          {loading ? "Calculating route…" : "Calculate route"}
        </button>
        <button
          type="button"
          disabled={!route}
          onClick={onClearRoute}
          className="rounded-lg border border-slate-300 px-3 py-2 text-xs font-semibold text-slate-700 disabled:opacity-40"
        >
          Clear route
        </button>
        <button
          type="button"
          disabled={!source && !destination && !route}
          onClick={onReset}
          className="rounded-lg border border-slate-300 px-3 py-2 text-xs font-semibold text-slate-700 disabled:opacity-40"
        >
          Reset all
        </button>
      </div>

      {route && (
        <div className="mt-5">
          <RouteSummary route={route} />
        </div>
      )}
      {comparison && (
        <section
          className="mt-4 rounded-xl border border-teal-200 bg-teal-50 p-4 text-xs"
          aria-label="Route comparison"
        >
          <h3 className="font-semibold text-teal-950">
            Route updated due to flood risk
          </h3>
          <div className="mt-3 grid grid-cols-2 gap-3">
            <p>
              Old: {Math.ceil(comparison.oldEtaSeconds / 60)} min ·{" "}
              {comparison.oldRiskLevel}
            </p>
            <p>
              New: {Math.ceil(comparison.newEtaSeconds / 60)} min ·{" "}
              {comparison.newRiskLevel}
            </p>
            <p>
              {comparison.etaDeltaSeconds >= 0 ? "+" : ""}
              {Math.round(comparison.etaDeltaSeconds)} sec
            </p>
            <p>Risk reduced by {comparison.riskReduction.toFixed(2)}</p>
          </div>
          <button
            type="button"
            onClick={onDismissComparison}
            className="mt-3 rounded border border-teal-300 px-2 py-1 font-semibold text-teal-900"
          >
            Dismiss comparison
          </button>
        </section>
      )}
    </aside>
  );
}
