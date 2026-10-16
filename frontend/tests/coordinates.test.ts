import { expect, test } from "vitest";
import {
  isValidGeoPoint,
  parseGeoPoint,
  toGeoJsonPosition,
} from "@/lib/geo/coordinates";

test("validates finite WGS84 coordinates", () => {
  expect(isValidGeoPoint({ latitude: 19.076, longitude: 72.8777 })).toBe(true);
  expect(isValidGeoPoint({ latitude: 91, longitude: 72 })).toBe(false);
  expect(isValidGeoPoint({ latitude: 19, longitude: Number.NaN })).toBe(false);
  expect(parseGeoPoint("", "72")).toBeNull();
  expect(parseGeoPoint("19", "181")).toBeNull();
});

test("converts the application model to GeoJSON longitude-latitude order", () => {
  expect(toGeoJsonPosition({ latitude: 19.076, longitude: 72.8777 })).toEqual([
    72.8777, 19.076,
  ]);
});
