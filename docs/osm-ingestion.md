# OpenStreetMap ingestion

Phase 4 converts a local OpenStreetMap XML extract into a versioned FloodGuard directed graph. The importer is intentionally separate from routing: it does not expose a route API and does not run Dijkstra or A*.

## Source strategy

The ingestion core reads uncompressed `.osm` XML files with Python's standard-library streaming `xml.etree.ElementTree.iterparse`. This keeps the parser dependency-free for small development extracts and prevents library-specific objects from crossing into the domain model. `.osm.pbf` is reserved for a later parser adapter; the current CLI rejects it clearly rather than pretending to support it.

The source file is local and its SHA-256 checksum is stored in `graph_versions.metadata`. Public Overpass or routing API calls are not part of the importer. Large extracts belong under the ignored `data/` directory and must not be committed.

## CLI

From `backend/`:

```sh
uv run --locked python -m app.ingestion.osm \
  --region tirupati \
  --name "Tirupati" \
  --file ../data/tirupati.osm
```

Use `--graph-version N` to request an explicit positive version, or omit it to allocate the next version for the region. Use `--dry-run` to parse, construct, validate, checksum and print statistics without database writes.

The first import creates the region from the graph bounding box as a WGS84 `MULTIPOLYGON`. Later imports reuse the region and create another graph version. A source checksum already imported for that region is rejected; a version number already present is also rejected. There is no silent replacement flag.

## Filtering and topology

The accepted vehicle classes are `motorway`, `motorway_link`, `trunk`, `trunk_link`, `primary`, `primary_link`, `secondary`, `secondary_link`, `tertiary`, `tertiary_link`, `residential`, `living_street`, `service` and `unclassified`. Footways, cycleways, paths, steps and pedestrian roads are excluded. Roads marked `access`, `motor_vehicle`, `motorcar` or `vehicle` as `no`, `private`, `agricultural` or `forestry` are skipped.

Each retained way is split at every OSM node reference. A normal way creates one edge in each direction. `oneway=yes`, `1` and `true` create only the source-order edge; `oneway=-1` creates only the reversed edge. `oneway=no` creates both. `junction=roundabout` is treated as source-order one-way. OSM node identity determines connectivity, so geometrically crossing bridge/tunnel lines without a shared OSM node remain disconnected.

The internal node and edge IDs are UUIDs. OSM node/way IDs are provenance fields. Every edge stores its graph version, way ID, segment index and direction (`1` or `-1`). Reverse geometries are explicitly reversed and always run from `source_node_id` to `target_node_id`.

## Distance and speed

The initial speed model uses a centralized road-class default table. Simple `maxspeed` values are accepted in kilometers per hour, and `mph`/`mi/h` values are converted using 1.609344. Unsupported or malformed values fall back to the class default and increment a warning statistic. Distance uses a haversine geodesic approximation in meters for the in-memory graph, then persists the result as `distance_m`. Base travel time is `distance_m / (speed_limit_kph * 1000 / 3600)`. Traffic, incidents, rainfall and flood risk are deliberately absent.

## Transactions and validation

Parsing, filtering, graph construction and validation happen before persistence. Persistence runs in the caller's one SQLAlchemy transaction: region, graph version, nodes and edges are flushed together and any exception rolls back the whole import. Validation checks node references, directed geometry endpoints, positive finite distance/time/speed, graph self-loops, and reports weakly connected components and largest-component percentage.

The database retains the existing Phase 2 constraints, including SRID 4326 typmods, composite graph-version foreign keys and OSM segment uniqueness. No Alembic migration was necessary.

## Known limitations

Turn-restriction relations, conditional access, lane-level semantics, maxspeed conditionals, destination restrictions, traffic, closures, elevation and ferry-specific vehicle policy are not modeled. The importer does not clip arbitrary planet data; developers should use a regional extract whose bounds are appropriate for the target region. The development fixture includes an overpass-style disconnected crossing and a roundabout for deterministic tests.

## Real data policy

A real regional extract should be downloaded separately, recorded with its source URL/provider, capture date and coverage, and passed through `--dry-run` before persistence. Do not commit the extract. Record actual node/way/edge counts and import duration in `docs/phase-4-verification.md` after a PostGIS-backed run.
