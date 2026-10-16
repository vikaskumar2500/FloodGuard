# Phase 5 routing

Phase 5 routes over one persisted FloodGuard graph version using baseline travel time. It does not use flood risk, traffic, turn restrictions, Redis, or an external routing engine.

## Architecture

`RoutingGraphRepository` resolves the newest graph version whose region covers both requested endpoints, finds nearest nodes with PostGIS geography distance, and loads that one graph version into an in-memory adjacency list. `routing.service` owns snapping, algorithm selection, metrics, geometry assembly and transactional persistence. Dijkstra and A* only receive routing-domain objects and know nothing about HTTP or SQLAlchemy.

The first implementation loads a manageable regional graph into memory for each calculation. A future graph provider/cache can be introduced behind the repository boundary; Redis caching is intentionally not implemented.

## Algorithms

Dijkstra uses a binary heap, a distance map and predecessor edge/node maps:

$$
dist[v] = \min(dist[v], dist[u] + w(u,v))
$$

Its adjacency-list complexity is $O((V + E) \log V)$ time and $O(V + E)$ space. Heap entries are immutable `(priority, counter, node, g_cost)` tuples. Improved entries are pushed rather than mutated, and stale entries are discarded when their `g_cost` no longer matches the best distance.

A* uses the same directed edges and accumulated travel time:

$$
f(n) = g(n) + h(n)
$$

The heuristic is:

$$
h(n) = \frac{d_{straight}(n, goal)}{v_{max}}
$$

where `d_straight` is haversine distance in meters and `v_max` is the maximum effective graph speed derived from `distance_m / base_travel_time_s`. Because every traversable edge speed is at most `v_max`, straight-line distance is no greater than the path distance still required, so this is a lower bound on remaining travel time. Therefore the heuristic is admissible and nonnegative, with `h(goal) = 0`. A* has the same worst-case complexity as Dijkstra.

## Snapping and graph isolation

The API receives WGS84 latitude/longitude. The repository resolves one graph version whose region covers both points, then performs nearest-node PostGIS geography lookup filtered by that graph version. The default maximum snap distance is 5,000 meters and is configurable with `MAX_ROUTE_SNAP_DISTANCE_M`. No nearby node produces a controlled 422 error.

A configurable `MAX_ROUTING_EXPANSIONS` limit prevents malformed or unexpectedly large graphs from running without bound. Graph validation rejects missing nodes, invalid coordinates, invalid weights, self-loops, and misoriented geometries before search.

## Geometry and persistence

Predecessors store exact edge IDs as well as predecessor nodes, so parallel edges remain distinguishable. Reconstructed edge geometries are concatenated in directed order and shared boundary coordinates are not duplicated. GeoJSON coordinates remain `[longitude, latitude]`.

The API calculates total distance by summing selected edge rows and ETA by summing their `base_travel_time_s`. Successful routes persist one `routes` row and ordered `route_segments` rows in the same transaction. The returned route ID is the persisted UUID and the selected graph version is returned and stored.

Phase 5 risk is unavailable, not zero: `riskScore` and segment risk scores are `null`, `riskModelActive` is `false`, and the route metadata identifies the baseline policy. Migration `0002_route_risk_optional` makes this explicit without changing migration `0001`.

## API

`POST /api/v1/routes/calculate` accepts:

```json
{
  "source": {"latitude": 19.076, "longitude": 72.8777},
  "destination": {"latitude": 19.09, "longitude": 72.89},
  "mode": "FASTEST",
  "algorithm": "ASTAR"
}
```

`algorithm` defaults to `ASTAR`; the only values are `ASTAR` and `DIJKSTRA`. FASTEST uses baseline travel time. BALANCED and SAFEST currently use the same baseline algorithm and explicitly report `riskModelActive: false`.

The response includes `routeId`, `graphVersionId`, `algorithm`, `mode`, `distanceMeters`, `estimatedTimeSeconds`, nullable `riskScore`, `expandedNodes`, `riskModelActive`, and a GeoJSON LineString. Invalid coordinates, unavailable graph coverage, excessive snap distance, no route, database failure and expansion limits return controlled problem responses.

## Frontend

The existing `frontend/lib/api/routes.ts` boundary now posts to the backend and validates the typed response. MapLibre source/layer ownership, markers, fit-bounds behavior, loading state and route panel structure remain unchanged. Backend failures are displayed directly as user-facing errors; there is no silent mock fallback.

## Limitations

The baseline engine does not model flood risk, live traffic, incidents, turn restrictions, conditional access, traffic signals, lane-level navigation, turn penalties, closures, time-dependent travel time, or dynamic rerouting. Phase 6 owns risk-weighted routing.
