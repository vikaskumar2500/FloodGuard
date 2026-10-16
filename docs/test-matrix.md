# FloodGuard Test Matrix

This matrix maps system capabilities to their respective test layers as verified in Phase 22.

| Capability               | Unit Tests | Integration Tests | Contract Tests | E2E (Browser) |
|--------------------------|------------|-------------------|----------------|---------------|
| **Routing Algorithm**    | ✓ (A* vs D)| ✓ (PostGIS)       |                | ✓             |
| **Risk / ML Fusion**     | ✓          | ✓                 | ✓ (Schema)     | ✓             |
| **Realtime Rerouting**   | ✓          | ✓ (Redis/SQS)     | ✓ (SSE)        | ✓             |
| **Messaging (SQS)**      | ✓ (Mock)   | ✓ (Real AWS/Local)| ✓ (Envelope)   |               |
| **Storage (S3)**         | ✓ (Mock)   | ✓ (Real AWS/Local)| ✓ (Manifest)   |               |
| **Observability**        | ✓          |                   |                |               |
| **Auth & Security**      | ✓          | ✓                 |                | ✓ (RBAC test) |
| **Assistant (Bedrock)**  | ✓ (Mock)   |                   | ✓ (Tool Schema)| ✓             |
| **Frontend Components**  | ✓          |                   |                | ✓             |

