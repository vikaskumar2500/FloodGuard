"use client";

import { useEffect, useState } from "react";
import { fetchCurrentWeather, type WeatherData } from "@/lib/api/environment";

export function EnvironmentStatus({
  latitude = 19.076,
  longitude = 72.8777,
}: {
  latitude?: number;
  longitude?: number;
}) {
  const [weather, setWeather] = useState<WeatherData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  useEffect(() => {
    let disposed = false;
    const controller = new AbortController();

    async function load() {
      try {
        const data = await fetchCurrentWeather(
          latitude,
          longitude,
          controller.signal,
        );
        if (!disposed) {
          setWeather(data);
          setError(false);
        }
      } catch {
        if (!disposed) {
          setError(true);
        }
      } finally {
        if (!disposed) {
          setLoading(false);
        }
      }
    }

    void load();
    const interval = setInterval(() => void load(), 60_000);

    return () => {
      disposed = true;
      controller.abort();
      clearInterval(interval);
    };
  }, [latitude, longitude]);

  if (loading && !weather) {
    return (
      <div className="flex items-center gap-1.5 text-xs text-slate-400">
        <span className="inline-block h-2 w-2 animate-pulse rounded-full bg-slate-300" />
        <span>Weather: loading...</span>
      </div>
    );
  }

  if (error && !weather) {
    return (
      <div
        className="flex items-center gap-1.5 text-xs text-slate-400"
        title="Environmental feed unavailable"
      >
        <span className="inline-block h-2 w-2 rounded-full bg-slate-300" />
        <span>Weather: offline</span>
      </div>
    );
  }

  if (!weather) return null;

  const freshnessColor =
    weather.freshness === "FRESH"
      ? "bg-emerald-500"
      : weather.freshness === "STALE"
        ? "bg-amber-500"
        : "bg-slate-400";

  const rainfallText =
    weather.rainfall_mm_per_hour !== null
      ? `${weather.rainfall_mm_per_hour.toFixed(1)} mm/h`
      : "No rain data";

  return (
    <div
      className="flex items-center gap-2 rounded-md border border-slate-200 bg-white/80 px-2.5 py-1 text-xs text-slate-700 shadow-sm backdrop-blur"
      data-testid="environment-status"
      title={`Source: ${weather.provider} (${weather.data_source_state}), Observed: ${new Date(weather.observed_at).toLocaleTimeString()}`}
    >
      <span className={`inline-block h-2 w-2 rounded-full ${freshnessColor}`} />
      <span className="font-medium text-slate-900">🌧️ {rainfallText}</span>
      {weather.temperature_c !== null && (
        <span className="text-slate-500">
          | {weather.temperature_c.toFixed(0)}°C
        </span>
      )}
      <span className="rounded bg-slate-100 px-1 py-0.2 text-[10px] font-mono text-slate-500">
        {weather.data_source_state === "MOCK" ? "MOCK" : weather.freshness}
      </span>
    </div>
  );
}
