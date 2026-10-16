"use client";

import dynamic from "next/dynamic";
import type { FloodMapProps } from "./flood-map";

const FloodMap = dynamic(() => import("./flood-map"), {
  ssr: false,
  loading: () => (
    <div
      className="grid h-full min-h-[420px] place-items-center bg-slate-100 text-sm text-slate-600"
      role="status"
    >
      Preparing map…
    </div>
  ),
});

export function MapShell(props: FloodMapProps) {
  return <FloodMap {...props} />;
}
