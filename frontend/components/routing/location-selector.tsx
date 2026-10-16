"use client";

import { useState } from "react";
import type { GeoPoint } from "@/lib/geo/coordinates";
import { formatCoordinate, parseGeoPoint } from "@/lib/geo/coordinates";

export function LocationSelector({
  label,
  point,
  active,
  onActivate,
  onChange,
  onClear,
}: Readonly<{
  label: "Source" | "Destination";
  point: GeoPoint | null;
  active: boolean;
  onActivate: () => void;
  onChange: (point: GeoPoint) => void;
  onClear: () => void;
}>) {
  const [latitude, setLatitude] = useState(point ? String(point.latitude) : "");
  const [longitude, setLongitude] = useState(
    point ? String(point.longitude) : "",
  );
  const [error, setError] = useState("");

  function apply() {
    const next = parseGeoPoint(latitude, longitude);
    if (!next) {
      setError("Enter latitude −90 to 90 and longitude −180 to 180.");
      return;
    }
    setError("");
    onChange(next);
  }

  return (
    <fieldset
      className={`location-fieldset ${active ? "location-fieldset--active" : ""}`}
    >
      <legend className="sr-only">{label} location</legend>
      <div className="flex items-center justify-between gap-2">
        <button
          type="button"
          onClick={onActivate}
          className="text-left text-sm font-semibold text-slate-900"
        >
          {label}{" "}
          {active && (
            <span className="text-xs font-medium text-teal-700">
              · map click active
            </span>
          )}
        </button>
        {point && (
          <button
            type="button"
            onClick={onClear}
            className="text-xs font-medium text-slate-500 underline underline-offset-2"
          >
            Clear
          </button>
        )}
      </div>
      {point && (
        <p className="mt-1 text-xs text-slate-500">
          {formatCoordinate(point.latitude)} lat,{" "}
          {formatCoordinate(point.longitude)} lng
        </p>
      )}
      <div className="mt-3 grid grid-cols-2 gap-2">
        <label className="coordinate-label">
          Latitude
          <input
            aria-label={`${label} latitude`}
            inputMode="decimal"
            value={latitude}
            onChange={(event) => setLatitude(event.target.value)}
            placeholder="19.0760"
          />
        </label>
        <label className="coordinate-label">
          Longitude
          <input
            aria-label={`${label} longitude`}
            inputMode="decimal"
            value={longitude}
            onChange={(event) => setLongitude(event.target.value)}
            placeholder="72.8777"
          />
        </label>
      </div>
      <button
        type="button"
        onClick={apply}
        className="mt-2 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-xs font-semibold text-slate-700 hover:bg-slate-50"
      >
        Set {label.toLowerCase()} coordinates
      </button>
      {error && (
        <p className="mt-2 text-xs text-red-700" role="alert">
          {error}
        </p>
      )}
    </fieldset>
  );
}
