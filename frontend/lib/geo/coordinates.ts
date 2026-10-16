export type GeoPoint = Readonly<{
  latitude: number;
  longitude: number;
}>;

export type GeoJsonPosition = readonly [longitude: number, latitude: number];

export function isValidGeoPoint(point: GeoPoint): boolean {
  return (
    Number.isFinite(point.latitude) &&
    point.latitude >= -90 &&
    point.latitude <= 90 &&
    Number.isFinite(point.longitude) &&
    point.longitude >= -180 &&
    point.longitude <= 180
  );
}

/** GeoJSON always uses [longitude, latitude], never display-order lat/lng. */
export function toGeoJsonPosition(point: GeoPoint): GeoJsonPosition {
  if (!isValidGeoPoint(point))
    throw new RangeError("Invalid geographic coordinates");
  return [point.longitude, point.latitude];
}

export function formatCoordinate(value: number): string {
  return value.toFixed(5);
}

export function parseGeoPoint(
  latitude: string,
  longitude: string,
): GeoPoint | null {
  if (latitude.trim() === "" || longitude.trim() === "") return null;
  const point = { latitude: Number(latitude), longitude: Number(longitude) };
  return isValidGeoPoint(point) ? point : null;
}
