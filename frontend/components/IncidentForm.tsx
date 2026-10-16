"use client";

import { useState } from "react";

export default function IncidentForm({
  onSubmit,
}: {
  onSubmit: (data: Record<string, unknown>) => void;
}) {
  const [type, setType] = useState("WATERLOGGING");
  const [severity, setSeverity] = useState("HIGH");
  const [desc, setDesc] = useState("");

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    onSubmit({
      incident_type: type,
      severity,
      description: desc,
      occurred_at: new Date().toISOString(),
    });
  };

  return (
    <div className="bg-white p-4 shadow-md rounded-md">
      <h3 className="font-bold mb-2">Report Incident</h3>
      <form onSubmit={handleSubmit} className="flex flex-col gap-2">
        <label>
          Type:
          <select
            value={type}
            onChange={(e) => setType(e.target.value)}
            className="border ml-2 w-full"
          >
            <option value="WATERLOGGING">Waterlogging</option>
            <option value="FLOODED_ROAD">Flooded Road</option>
            <option value="ROAD_BLOCKED">Road Blocked</option>
            <option value="FALLEN_TREE">Fallen Tree</option>
          </select>
        </label>
        <label>
          Severity:
          <select
            value={severity}
            onChange={(e) => setSeverity(e.target.value)}
            className="border ml-2 w-full"
          >
            <option value="LOW">Low</option>
            <option value="MODERATE">Moderate</option>
            <option value="HIGH">High</option>
            <option value="SEVERE">Severe</option>
          </select>
        </label>
        <label>
          Description:
          <textarea
            value={desc}
            onChange={(e) => setDesc(e.target.value)}
            className="border w-full"
          />
        </label>
        <button type="submit" className="bg-blue-600 text-white p-2 rounded">
          Submit
        </button>
      </form>
    </div>
  );
}
