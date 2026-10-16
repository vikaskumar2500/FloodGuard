"use client";

import { useEffect, useState } from "react";
import { StatusCard, type DisplayStatus } from "@/components/status-card";
import { apiBaseUrl, fetchReadiness, type ReadinessReport } from "@/lib/health";

export function SystemStatus({ compact = false }: { compact?: boolean }) {
  const [report, setReport] = useState<ReadinessReport | null>(null);
  const [error, setError] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);
  const [checking, setChecking] = useState(true);

  useEffect(() => {
    let disposed = false;
    let controller: AbortController | undefined;
    let timeout: ReturnType<typeof setTimeout> | undefined;
    async function refresh() {
      controller?.abort();
      clearTimeout(timeout);
      controller = new AbortController();
      timeout = setTimeout(() => controller?.abort(), 5000);
      setChecking(true);
      try {
        const result = await fetchReadiness(controller.signal);
        if (!disposed) {
          setReport(result);
          setError(false);
        }
      } catch {
        if (!disposed) {
          setReport(null);
          setError(true);
        }
      } finally {
        clearTimeout(timeout);
        if (!disposed) setChecking(false);
      }
    }
    void refresh();
    const poll = setInterval(() => void refresh(), 30000);
    return () => {
      disposed = true;
      controller?.abort();
      clearTimeout(timeout);
      clearInterval(poll);
    };
  }, [refreshKey]);

  const missing: DisplayStatus = error ? "unavailable" : "checking";
  const postgres: DisplayStatus = report
    ? report.dependencies.postgres.status === "unavailable"
      ? "unavailable"
      : report.dependencies.postgis.status === "unavailable"
        ? "degraded"
        : "healthy"
    : missing;

  if (compact) {
    const values: Array<[string, DisplayStatus]> = [
      ["API", report ? "healthy" : missing],
      ["Database", postgres],
      ["Redis", report?.dependencies.redis.status ?? missing],
    ];
    return (
      <details className="relative">
        <summary className="status-summary" aria-label="Open system status">
          <span
            className={`status-dot status-dot--${report?.ready ? "healthy" : error ? "unavailable" : "checking"}`}
          />
          System status
        </summary>
        <div className="status-popover">
          <p className="mb-3 text-xs font-semibold text-slate-900">
            Infrastructure connectivity
          </p>
          <ul className="grid gap-2">
            {values.map(([name, status]) => (
              <li
                key={name}
                className="flex items-center justify-between gap-6 text-xs text-slate-700"
              >
                {name}
                <span className={`status-label status-label--${status}`}>
                  {status}
                </span>
              </li>
            ))}
          </ul>
          <button
            type="button"
            disabled={checking}
            onClick={() => setRefreshKey((key) => key + 1)}
            className="mt-3 w-full rounded-md border border-slate-200 px-2 py-1.5 text-xs font-medium"
          >
            {checking ? "Checking…" : "Refresh"}
          </button>
        </div>
      </details>
    );
  }

  return (
    <section aria-labelledby="system-status-heading">
      <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div>
          <h2
            id="system-status-heading"
            className="text-xl font-semibold tracking-tight"
          >
            System status
          </h2>
          <p
            className="mt-2 text-sm text-slate-500"
            role="status"
            aria-live="polite"
          >
            {error
              ? "Unable to reach the API. Check the backend and try again."
              : !report
                ? "Checking local services…"
                : report.ready
                  ? report.status === "degraded"
                    ? "Ready with reduced dependency availability."
                    : "All required services are connected."
                  : "The API is responding, but the system is not ready."}
          </p>
        </div>
        <button
          type="button"
          disabled={checking}
          onClick={() => setRefreshKey((key) => key + 1)}
          className="rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50 disabled:cursor-wait disabled:opacity-50"
        >
          {checking ? "Checking…" : "Refresh status"}
        </button>
      </div>
      <div className="grid gap-4 sm:grid-cols-3">
        <StatusCard
          name="API"
          status={report ? "healthy" : missing}
          description={
            report
              ? `FastAPI is responding · v${report.version}`
              : "Backend process connectivity"
          }
        />
        <StatusCard
          name="PostgreSQL"
          status={postgres}
          description={
            report
              ? `${report.dependencies.postgres.message}. ${report.dependencies.postgis.message}.`
              : "Database and PostGIS extension connectivity"
          }
        />
        <StatusCard
          name="Redis"
          status={report?.dependencies.redis.status ?? missing}
          description={
            report?.dependencies.redis.message ?? "Redis connection and ping"
          }
        />
      </div>
      <div className="mt-5 flex flex-wrap justify-between gap-3 text-xs text-slate-500">
        <p>Refreshes every 30 seconds · Connectivity status only</p>
        <a
          href={`${apiBaseUrl}/docs`}
          target="_blank"
          rel="noreferrer"
          className="font-medium text-teal-700 underline underline-offset-4"
        >
          Open API documentation ↗
        </a>
      </div>
    </section>
  );
}
