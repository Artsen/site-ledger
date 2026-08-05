# Graph Performance

PR 9 hardens the scan-specific topology graph without changing its product purpose.

## Central Configuration

The backend owns graph limits in `app.services.graph_config`. The frontend reads shared values from:

```text
GET /api/graph/capabilities
```

Current defaults:

- Default nodes: 100
- Maximum nodes: 3,000
- Default edges: 250
- Maximum edges: 10,000
- Default focus hops: 1
- Maximum focus hops: 3
- Sample anchors per edge: 5
- Default edge occurrence page: 50
- Maximum edge occurrence page: 200

These values preserve the runtime caps that existed after PR 8. The previous documentation was split:
README listed 3,000 nodes and 10,000 edges, while `docs/website-graph.md` still listed 1,500 nodes
and 5,000 edges. PR 9 keeps the larger current runtime caps because the 3D renderer remained usable
in recent local testing at those caps after graph rendering optimizations, but keeps conservative
defaults for ordinary graph loads.

## Node Selection

Fetched page node filtering, ranking, exact available count, and limiting now happen in SQL before
ORM snapshot rows are loaded. Ranking remains deterministic:

1. Starting page
2. Lower crawl depth
3. Higher unique inbound source pages
4. Higher unique outbound target pages
5. Normalized URL
6. Snapshot ID

Metric subqueries are used for filtering and ranking. Detailed metric values are loaded only for the
selected node resources, not for every snapshot in the scan.

## Edge Aggregation

Edges remain one directed edge per source snapshot and target resource. Aggregation stays set-based:
occurrence count, unique anchor count, nofollow count, empty-anchor count, first/last discovery,
scope-decision counts, and DOM-region counts are calculated with SQL aggregate queries.

Edge limiting remains deterministic and bounded. The graph summary reports available edges,
returned edges, and total represented occurrences for all available filtered edges.

## Occurrence Pagination

The edge occurrence endpoint is split into two bounded operations:

- A SQL aggregate summary for the complete edge.
- A paginated row query for the requested occurrence page.

The endpoint no longer loads all occurrences to calculate the edge summary. A regression fixture with
10,000 repeated occurrences verifies that requesting 50 rows returns 50 row objects while the summary
still reports all 10,000 stored occurrences.

## Focus Neighborhoods

Focused graph traversal validates that the focus snapshot belongs to the scan, then expands incoming
and outgoing page-link relationships with one batched query per hop. The traversal is bounded by
configured focus hops and graph node limits, detects cycles through a visited set, and preserves
direction when edges are aggregated for the returned nodes.

## Frontend Boundaries

`ScanGraphView` now treats graph capabilities as server state. Display settings such as color,
labels, edge width, and background remain renderer-only state and do not change the graph API query.

The graph data adapter is split into pure modules:

- `adapterTypes.ts`
- `coordinates.ts`
- `nodeSizing.ts`
- `nodeCategories.ts`
- `edgeStyling.ts`
- `graphDataAdapter.ts`

Renderer imports remain isolated in the lazy 2D and 3D renderer modules.

## Bundle Measurements

Measured with `npm run build` on this branch:

- Initial app chunk: 397.00 kB minified, 114.72 kB gzip
- 2D renderer chunk: 4.57 kB minified, 2.23 kB gzip
- 3D renderer chunk: 1,386.88 kB minified, 375.20 kB gzip

The 3D chunk remains lazy and continues to trigger Vite's large-chunk warning. `npm ls` shows a
single deduped `three@0.185.1` copy through `react-force-graph-3d`, `3d-force-graph`,
`three-forcegraph`, and `three-render-objects`.

## Benchmark Command

Use a completed local scan ID:

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
python -m app.graph_benchmark 1
```

To include a paginated edge occurrence check:

```powershell
python -m app.graph_benchmark 1 --edge-id 8-2
```

The command reports graph query count, elapsed milliseconds, serialized response bytes, returned and
available nodes/edges, total occurrences, and optional occurrence-page query metrics. It is intended
for repeatable local comparisons, not strict wall-clock CI assertions.

## Practical Expectations

Defaults are intended for quick inspection of ordinary scans. Hard caps are available for larger
scans, but users should prefer host/path/depth filters or focused neighborhoods when a scan contains
thousands of pages or very dense navigation. This PR does not claim support for tens of thousands of
visible nodes in one browser-rendered graph.

## Known Limitations

- SQLite query plans are less sophisticated than PostgreSQL plans for large aggregate workloads.
- Exact available-node counts still require an aggregate count over the filtered candidate query.
- The 3D renderer library dominates the lazy 3D chunk size.
- No graph coordinates, camera state, or saved graph views are persisted.
