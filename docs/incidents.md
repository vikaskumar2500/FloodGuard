# Incident Management

The Incident Management module allows users to report flooding or other hazards, clusters reports spatially, computes confidence scores, and allows operators to verify or reject them.

## Key Features
- **Spatial Clustering**: Groups reports within 50m using PostGIS.
- **Trust Scoring**: Confidence based on reporter weight, freshness, and corroboration.
- **Realtime Integration**: Verified severe incidents update `RuntimeRiskState` and trigger reroutes.
