import type { ReadinessReport } from "@/lib/health";

export const healthyReport: ReadinessReport = {
  status: "healthy",
  ready: true,
  service: "floodguard-api",
  version: "0.1.0",
  request_id: "test",
  dependencies: {
    postgres: { status: "healthy", message: "Database reachable" },
    postgis: { status: "healthy", message: "PostGIS extension available" },
    redis: { status: "healthy", message: "Redis reachable" },
  },
};
