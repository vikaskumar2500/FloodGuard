"use client";

import { useEffect, useReducer, useState } from "react";
import { EnvironmentStatus } from "@/components/environment-status";
import { MapShell } from "@/components/map/map-shell";
import { RoutePanel } from "@/components/routing/route-panel";
import { SystemStatus } from "@/components/system-status";
import { calculateRoute, type RouteMode } from "@/lib/api/routes";
import type { GeoPoint } from "@/lib/geo/coordinates";
import {
  initialRouteState,
  routeLifecycleReducer,
} from "@/lib/realtime/route-lifecycle";
import { subscribeToRoute } from "@/lib/realtime/routes";

export function FloodGuardWorkspace() {
  const [source, setSource] = useState<GeoPoint | null>(null);
  const [destination, setDestination] = useState<GeoPoint | null>(null);
  const [mode, setMode] = useState<RouteMode>("BALANCED");
  const [selectionMode, setSelectionMode] = useState<"source" | "destination">(
    "source",
  );
  const [routeState, dispatch] = useReducer(
    routeLifecycleReducer,
    initialRouteState,
  );
  const route = routeState.route;
  const loading = routeState.lifecycle === "CALCULATING";
  const [error, setError] = useState("");

  useEffect(() => {
    if (!route?.routeId) return;
    const subscription = subscribeToRoute(route.routeId, {
      onEvent: (event) => dispatch({ type: "EVENT", event }),
      onReconnecting: () => dispatch({ type: "RECONNECTING" }),
    });
    return () => subscription.close();
  }, [route?.routeId]);

  function changeSource(point: GeoPoint | null) {
    setSource(point);
    dispatch({ type: "CLEAR" });
    setError("");
    if (point) setSelectionMode("destination");
  }

  function changeDestination(point: GeoPoint | null) {
    setDestination(point);
    dispatch({ type: "CLEAR" });
    setError("");
  }

  function handleMapSelect(point: GeoPoint) {
    if (selectionMode === "source") changeSource(point);
    else changeDestination(point);
  }

  async function handleCalculate() {
    if (!source || !destination || loading) return;
    dispatch({ type: "CALCULATING" });
    setError("");
    try {
      dispatch({
        type: "CALCULATED",
        route: await calculateRoute({ source, destination, mode }),
      });
    } catch (routeError) {
      dispatch({ type: "CLEAR" });
      setError(
        routeError instanceof Error
          ? routeError.message
          : "The route could not be calculated. Check both locations and try again.",
      );
    }
  }

  function handleUseLocation() {
    setError("");
    if (!("geolocation" in navigator)) {
      setError(
        "Location is unavailable in this browser. Enter coordinates instead.",
      );
      return;
    }
    navigator.geolocation.getCurrentPosition(
      ({ coords }) =>
        changeSource({
          latitude: coords.latitude,
          longitude: coords.longitude,
        }),
      (failure) => {
        const message =
          failure.code === 1
            ? "Location permission was denied. Enter source coordinates instead."
            : failure.code === 3
              ? "Location request timed out. Try again or enter coordinates."
              : "Your location is currently unavailable. Enter coordinates instead.";
        setError(message);
      },
      { enableHighAccuracy: false, timeout: 8000, maximumAge: 60_000 },
    );
  }

  return (
    <main className="app-shell">
      <header className="app-header">
        <div className="flex items-center gap-3">
          <span className="brand-mark" aria-hidden="true">
            FG
          </span>
          <div>
            <p className="text-base font-semibold tracking-tight text-slate-950">
              FloodGuard
            </p>
            <p className="hidden text-[11px] text-slate-500 sm:block">
              Real-Time Flood Intelligence &amp; Safe Routing
            </p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <EnvironmentStatus />
          <SystemStatus compact />
        </div>
      </header>
      <div className="workspace-grid">
        <div className="panel-region">
          <RoutePanel
            source={source}
            destination={destination}
            mode={mode}
            route={route}
            selectionMode={selectionMode}
            loading={loading}
            error={error}
            lifecycle={routeState.lifecycle}
            lifecycleMessage={routeState.message}
            comparison={routeState.comparison}
            onDismissComparison={() => dispatch({ type: "DISMISS_COMPARISON" })}
            onSourceChange={changeSource}
            onDestinationChange={changeDestination}
            onModeChange={(nextMode) => {
              setMode(nextMode);
              dispatch({ type: "CLEAR" });
            }}
            onSelectionModeChange={setSelectionMode}
            onCalculate={() => void handleCalculate()}
            onClearRoute={() => {
              dispatch({ type: "CLEAR" });
              setError("");
            }}
            onReset={() => {
              setSource(null);
              setDestination(null);
              dispatch({ type: "CLEAR" });
              setError("");
              setSelectionMode("source");
            }}
            onUseLocation={handleUseLocation}
          />
        </div>
        <div className="map-region">
          <MapShell
            source={source}
            destination={destination}
            route={route}
            previousRoute={routeState.previousRoute}
            selectionMode={selectionMode}
            onMapSelect={handleMapSelect}
            onMapError={setError}
          />
        </div>
      </div>
    </main>
  );
}
