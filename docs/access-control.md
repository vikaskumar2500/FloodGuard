# Access Control Matrix

This matrix defines the authorization required for various capabilities across the system.

| Capability | Anonymous | USER | OPERATOR | ADMIN | SYSTEM |
| --- | --- | --- | --- | --- | --- |
| Route Calculation | Yes | Yes | Yes | Yes | No |
| Route SSE Subscribe | No | Yes (Own) | Yes | Yes | No |
| Incident Submit | No | Yes | Yes | Yes | Yes |
| Incident View | Yes | Yes | Yes | Yes | Yes |
| Incident Moderate (Verify/Reject/Resolve) | No | No | Yes | Yes | No |
| Assistant (Chat) | No | Yes | Yes | Yes | No |
| DLQ Inspect / Replay | No | No | No | Yes | Yes |
| Simulation Inject | No | No | No | Yes | No |
| System Status (Internal) | No | No | Yes | Yes | Yes |
| Artifact Admin | No | No | No | Yes | Yes |

*Note: Own implies the user must be the owner of the route.*
