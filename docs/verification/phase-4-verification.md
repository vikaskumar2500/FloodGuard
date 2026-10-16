# Phase 4 verification

## Fixture dry run

Executed from `backend/`:

```sh
uv run --locked python -m app.ingestion.osm \
  --region fixture-region \
  --file tests/fixtures/tiny.osm \
  --dry-run
```

Observed statistics:

| Metric | Value |
| --- | ---: |
| OSM nodes parsed | 8 |
| OSM ways parsed | 8 |
| accepted road ways | 6 |
| excluded road ways | 1 |
| restricted roads skipped | 1 |
| graph nodes | 8 |
| directed edges | 12 |
| one-way ways | 3 |
| two-way ways | 3 |
| invalid/skipped segments | 0 |
| malformed speed tags | 1 |
| total graph distance | 1825.18 m |
| weakly connected components | 2 |
| largest component | 75.0% |

The checksum recorded for this fixture run was `719718cac4a054ddec3023d136e047db48e50053dd036a8a597f8f0e1030a7a8`.

## Automated verification

- OSM parser and graph semantics: 4 passed.
- Ingestion lint: passed.
- Ingestion format check: passed.
- Python compilation: passed.
- PostGIS persistence test: added and marked integration; not run because the Docker Compose/PostGIS runtime was unavailable on the verification host.

## Real development region

No real regional OSM extract was imported. The repository does not contain a committed `.osm`/`.osm.pbf` dataset, and the local Docker Compose command is unavailable on the current host. The importer is ready for a separately downloaded regional `.osm` extract; its checksum, coverage and database counts should be recorded here after that run.

## Performance

No real-region ingestion duration or throughput measurement was taken. The fixture dry run is a correctness check, not a performance baseline.
