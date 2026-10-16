"use client";

export default function IncidentPanel({
  incident,
  onVerify,
  onReject,
  onResolve,
}: {
  incident: {
    incident_type: string;
    status: string;
    severity: string;
    confidence: number;
    description: string;
  } | null;
  onVerify: () => void;
  onReject: () => void;
  onResolve: () => void;
}) {
  if (!incident) return null;

  return (
    <div className="bg-white p-4 shadow-md rounded-md absolute right-4 top-4 w-80">
      <h3 className="font-bold">{incident.incident_type}</h3>
      <p>
        Status: <span className="font-semibold">{incident.status}</span>
      </p>
      <p>Severity: {incident.severity}</p>
      <p>Confidence: {(incident.confidence * 100).toFixed(0)}%</p>
      <p className="text-sm mt-2">{incident.description}</p>

      {incident.status !== "VERIFIED" &&
        incident.status !== "RESOLVED" &&
        incident.status !== "REJECTED" && (
          <div className="flex gap-2 mt-4">
            <button
              onClick={onVerify}
              className="bg-green-600 text-white p-1 rounded flex-1"
            >
              Verify
            </button>
            <button
              onClick={onReject}
              className="bg-red-600 text-white p-1 rounded flex-1"
            >
              Reject
            </button>
          </div>
        )}
      {incident.status === "VERIFIED" && (
        <button
          onClick={onResolve}
          className="bg-blue-600 text-white p-1 rounded mt-4 w-full"
        >
          Resolve
        </button>
      )}
    </div>
  );
}
