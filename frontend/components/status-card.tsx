import type { HealthStatus } from "@/lib/health";

export type DisplayStatus = HealthStatus | "checking";
const labels: Record<DisplayStatus, string> = {
  healthy: "Healthy",
  degraded: "Degraded",
  unavailable: "Unavailable",
  checking: "Checking…",
};
const styles: Record<DisplayStatus, string> = {
  healthy: "bg-teal-50 text-teal-800 ring-teal-600/20",
  degraded: "bg-amber-50 text-amber-800 ring-amber-600/20",
  unavailable: "bg-red-50 text-red-800 ring-red-600/20",
  checking: "bg-slate-100 text-slate-600 ring-slate-400/20",
};

export function StatusCard({
  name,
  status,
  description,
}: {
  name: string;
  status: DisplayStatus;
  description: string;
}) {
  return (
    <article
      aria-label={`${name} status`}
      className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm"
    >
      <div className="mb-6 flex items-center justify-between gap-3">
        <h3 className="text-base font-semibold">{name}</h3>
        <span
          className={`rounded-full px-2.5 py-1 text-xs font-medium ring-1 ring-inset ${styles[status]}`}
        >
          {labels[status]}
        </span>
      </div>
      <p className="text-sm leading-6 text-slate-500">{description}</p>
    </article>
  );
}
