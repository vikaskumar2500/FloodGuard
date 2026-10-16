export type HealthStatus = "healthy" | "degraded" | "unavailable";
export type DependencyHealth = {
  status: "healthy" | "unavailable";
  message: string;
};
export type ReadinessReport = {
  status: HealthStatus;
  ready: boolean;
  service: string;
  version: string;
  request_id: string;
  dependencies: {
    postgres: DependencyHealth;
    postgis: DependencyHealth;
    redis: DependencyHealth;
  };
};

export const apiBaseUrl = (
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000"
).replace(/\/$/, "");
export const apiPrefix = process.env.NEXT_PUBLIC_API_V1_PREFIX ?? "/api/v1";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isDependency(value: unknown): value is DependencyHealth {
  return (
    isRecord(value) &&
    (value.status === "healthy" || value.status === "unavailable") &&
    typeof value.message === "string"
  );
}

function isReadiness(value: unknown): value is ReadinessReport {
  return (
    isRecord(value) &&
    ["healthy", "degraded", "unavailable"].includes(String(value.status)) &&
    typeof value.ready === "boolean" &&
    typeof value.service === "string" &&
    typeof value.version === "string" &&
    typeof value.request_id === "string" &&
    isRecord(value.dependencies) &&
    isDependency(value.dependencies.postgres) &&
    isDependency(value.dependencies.postgis) &&
    isDependency(value.dependencies.redis)
  );
}

export async function fetchReadiness(
  signal: AbortSignal,
): Promise<ReadinessReport> {
  const response = await fetch(`${apiBaseUrl}${apiPrefix}/health/ready`, {
    signal,
    cache: "no-store",
  });
  // 503 is an expected dependency-health response, not necessarily a dead API.
  if (response.status !== 200 && response.status !== 503)
    throw new Error("Health request failed");
  const body: unknown = await response.json();
  if (!isReadiness(body)) throw new Error("Unexpected health response");
  return body;
}
