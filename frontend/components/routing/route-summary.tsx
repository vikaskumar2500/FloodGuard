import type { RouteResponse } from "@/lib/api/routes";

export function RouteSummary({ route }: { route: RouteResponse }) {
  const maxSegmentMlProb = route.riskSegments.reduce<number | null>(
    (max, seg) => {
      if (seg.mlProbability != null) {
        return max === null
          ? seg.mlProbability
          : Math.max(max, seg.mlProbability);
      }
      return max;
    },
    null,
  );

  return (
    <section
      className="rounded-xl bg-slate-900 p-4 text-white"
      aria-labelledby="route-summary-title"
    >
      <div className="flex items-center justify-between gap-3">
        <h3 id="route-summary-title" className="text-sm font-semibold">
          Route summary
        </h3>
        <div className="flex items-center gap-1.5">
          {route.ml && (
            <span
              className={`rounded-full px-2 py-0.5 text-[10px] font-semibold tracking-wide ${
                route.ml.mode === "ACTIVE"
                  ? "bg-purple-900/60 text-purple-200 border border-purple-500/40"
                  : route.ml.mode === "SHADOW"
                    ? "bg-amber-900/60 text-amber-200 border border-amber-500/40"
                    : "bg-slate-800 text-slate-400 border border-slate-700"
              }`}
            >
              ML: {route.ml.mode}
            </span>
          )}
          <span className="rounded-full bg-white/10 px-2 py-1 text-[10px] font-semibold tracking-wide">
            {route.riskModelActive ? "RISK ACTIVE" : "RISK UNAVAILABLE"}
          </span>
        </div>
      </div>
      <dl className="mt-4 grid grid-cols-2 gap-4 text-xs">
        <div>
          <dt className="text-slate-400">Distance</dt>
          <dd className="mt-1 text-base font-semibold">
            {(route.distanceMeters / 1000).toFixed(1)} km
          </dd>
        </div>
        <div>
          <dt className="text-slate-400">ETA</dt>
          <dd className="mt-1 text-base font-semibold">
            {Math.ceil(route.estimatedTimeSeconds / 60)} min
          </dd>
        </div>
        <div>
          <dt className="text-slate-400">Mode</dt>
          <dd className="mt-1 font-semibold">{route.mode}</dd>
        </div>
        <div>
          <dt className="text-slate-400">Risk</dt>
          <dd className="mt-1 font-semibold">
            {route.riskLevel} ·{" "}
            {route.riskScore === null
              ? "Not available"
              : `${Math.round(route.riskScore * 100)}%`}
          </dd>
        </div>
        <div>
          <dt className="text-slate-400">Confidence</dt>
          <dd className="mt-1 font-semibold">
            {Math.round(route.riskConfidence * 100)}%
          </dd>
        </div>
        <div>
          <dt className="text-slate-400">Algorithm</dt>
          <dd className="mt-1 font-semibold">{route.algorithm}</dd>
        </div>
        {route.ml &&
          route.ml.mode !== "DISABLED" &&
          maxSegmentMlProb !== null && (
            <div className="col-span-2 rounded bg-slate-800/60 p-2 border border-slate-700/50">
              <dt className="text-slate-400">ML Flood Probability</dt>
              <dd className="mt-0.5 text-xs font-semibold text-purple-300">
                {Math.round(maxSegmentMlProb * 100)}% peak edge probability (
                {route.ml.modelVersion})
              </dd>
            </div>
          )}
      </dl>
      <p className="mt-4 border-t border-white/10 pt-3 text-[11px] leading-5 text-slate-300">
        {route.riskModelActive && route.riskSegments.length > 0
          ? route.riskSegments[0].explanation
          : "No current environmental evidence was associated with this route."}
      </p>
      {route.ml?.provenanceWarning && (
        <p className="mt-1 text-[10px] text-amber-400/80 italic">
          {route.ml.provenanceWarning}
        </p>
      )}
    </section>
  );
}
