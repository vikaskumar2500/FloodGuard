import { apiBaseUrl } from "@/lib/health";

export interface WeatherData {
  provider: string;
  latitude: number;
  longitude: number;
  observed_at: string;
  rainfall_mm_per_hour: number | null;
  temperature_c: number | null;
  humidity_percent: number | null;
  wind_speed_mps: number | null;
  source_quality: string;
  data_source_state: string;
  freshness: "FRESH" | "STALE" | "EXPIRED";
}

export async function fetchCurrentWeather(
  latitude: number = 19.076,
  longitude: number = 72.8777,
  signal?: AbortSignal,
): Promise<WeatherData> {
  const url = `${apiBaseUrl}/api/v1/environment/weather?latitude=${latitude}&longitude=${longitude}`;
  const response = await fetch(url, {
    method: "GET",
    headers: { Accept: "application/json" },
    signal,
  });
  if (!response.ok) {
    throw new Error(`Weather fetch failed: ${response.status}`);
  }
  return response.json();
}
