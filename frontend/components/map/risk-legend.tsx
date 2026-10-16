const levels = [
  ["Low", "bg-teal-500"],
  ["Moderate", "bg-amber-400"],
  ["High", "bg-orange-600"],
  ["Severe", "bg-red-700"],
] as const;

export function RiskLegend() {
  return (
    <details className="map-card absolute right-3 bottom-3 z-10 w-36" open>
      <summary className="cursor-pointer text-xs font-semibold text-slate-800">
        Flood risk legend
      </summary>
      <ul className="mt-2 grid gap-1.5 text-[11px] text-slate-700">
        {levels.map(([label, color]) => (
          <li className="flex items-center gap-2" key={label}>
            <span
              className={`size-2.5 rounded-sm ${color}`}
              aria-hidden="true"
            />
            {label} risk
          </li>
        ))}
      </ul>
      <p className="mt-2 text-[10px] leading-4 text-slate-500">
        Deterministic route evidence
      </p>
    </details>
  );
}
