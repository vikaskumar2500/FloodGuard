# FloodGuard interactive map frontend

Phase 3 provides a browser-only MapLibre workspace with mock route data. It does not query the Phase 2 road topology, calculate a road path, assess flood risk or create route records. The UI labels generated paths and summaries as mock/demo output.

## Map and component architecture

MapLibre GL JS is used directly. This keeps ownership of the long-lived map instance, sources, layers, controls and cleanup explicit while retaining vector-layer, GeoJSON-update and future clustering capabilities. The style defaults to `https://demotiles.maplibre.org/style.json` and is configurable with `NEXT_PUBLIC_MAP_STYLE_URL`; no private token is stored.

```text
FloodGuardWorkspace                 client domain state and orchestration
├── RoutePanel                      inputs, mode, actions and summary
│   ├── LocationSelector            validated coordinate alternative
│   └── RouteSummary                labelled mock metrics
├── MapShell                        client-only dynamic import; SSR boundary
│   └── FloodMap                    MapLibre instance and click events
│       ├── LocationMarker helpers  source/destination DOM markers
│       ├── mock-route GeoJSON      persistent source and line layer
│       └── RiskLegend              static future-layer legend
└── SystemStatus                    compact existing readiness display
```

`MapShell` dynamically loads only `FloodMap` with `ssr: false`; the rest of the page keeps normal Next.js rendering. MapLibre CSS is imported once by the root layout. `FloodMap` constructs one map after mount, registers controls and listeners once, and keeps current React callbacks in refs. On unmount it removes both markers and calls `map.remove()`, releasing controls and event listeners. Development hot reload therefore does not accumulate map instances.

After map load, one `GeoJSONSource` named `mock-route` and one line layer are added. Recalculation calls `setData` and changes the centralized mode color without recreating the map or source. A route builds `LngLatBounds` and calls `fitBounds`; clearing sends an empty LineString. Source and destination use distinct labelled marker helpers.

Style/tile errors show a user-facing warning while coordinate controls remain usable. Initialization, route and geolocation failures use the shared route-panel alert. Map tiles are an external display dependency and require internet access; unit tests mock MapLibre and make no tile requests.

## Coordinates and GeoJSON

Application state uses a named `GeoPoint` with `latitude` and `longitude`. Raw tuples are confined to the map boundary. `toGeoJsonPosition` converts a validated point to `[longitude, latitude]`, as required by GeoJSON and MapLibre.

Latitude must be finite and inside `[-90, 90]`; longitude must be finite and inside `[-180, 180]`. Reusable TypeScript validation is authoritative rather than HTML constraints. Display text labels `lat` and `lng` explicitly.

The active map-click target is highlighted. Setting a source advances selection to destination; either heading reactivates its target. Coordinate entry provides a keyboard-accessible alternative. Changing either point or mode clears a stale mock route.

## Mock route boundary

`lib/api/routes.ts` owns `RouteMode`, `RouteRequest`, `RouteResponse`, a GeoJSON LineString type and `calculateRoute(request)`. The request matches the future `POST /api/v1/routes/calculate` source/destination/mode shape. Phase 5 can replace this function body with the configured API client and response mapping without changing the workspace, panel or map contracts.

The current implementation creates a deterministic three-coordinate LineString through a small mode-specific visual bend. Distance, time and risk are fixed synthetic metadata per mode; the browser performs no authoritative road distance or flood-risk calculation. The algorithm is the literal `MOCK`, never A* or Dijkstra. Invalid or identical endpoints are rejected.

## State and responsive behavior

`FloodGuardWorkspace` keeps source, destination, selection target, mode, route, loading and error in focused React state. The map instance remains internal to `FloodMap`. Redux and another UI framework were not introduced.

Desktop/tablet uses a fixed header, independently scrollable 22-rem route panel and dominant remaining map. Below 768px the map appears first at roughly 57% of viewport height and the route controls form a raised sheet below it, so controls do not permanently cover the map. The risk legend is collapsible.

## Geolocation privacy

The Geolocation API runs only after “Use my location as source” is clicked. It requests one position with an eight-second timeout, no watch and no high-accuracy requirement. The point remains in component memory and is sent to no backend in Phase 3. Permission denial, timeout, unavailable API and position failure each direct the user to coordinate entry.

## Verification scope

Domain interaction tests mock the map component; lifecycle tests mock MapLibre itself. Coverage includes page rendering, sequential selection, validation, disabled/enabled calculation, mode switching, deterministic LineString output, summary, clear/reset, map and route errors, geolocation denial, source/layer updates, route fitting and map removal. A real browser check remains necessary for WebGL, style/tile loading and responsive visual behavior.
