import { useQuery } from "@tanstack/react-query";
import { Suspense, lazy, useEffect, useMemo, useRef, useState, type MutableRefObject } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { getGraphEdgeOccurrences, getScanGraph } from "../../api/client";
import { Button } from "../../components/ui/Button";
import { EmptyState } from "../../components/ui/EmptyState";
import { ErrorBanner } from "../../components/ui/ErrorBanner";
import { LoadingBlock } from "../../components/ui/Loading";
import { inputClass } from "../../components/ui/styles";
import type { GraphDisplaySettings, GraphEdge } from "../../types/graph";
import type { Scan } from "../../types/scans";
import { formatDate, formatStatus, isTerminalStatus, plural } from "../../utils/format";
import type { GraphRendererHandle } from "./GraphRendererTypes";
import { adaptGraphData, type RendererEdge, type RendererNode } from "./graphDataAdapter";

const TwoDimensionalGraphRenderer = lazy(() => import("./TwoDimensionalGraphRenderer").then((module) => ({ default: module.TwoDimensionalGraphRenderer })));
const ThreeDimensionalGraphRenderer = lazy(() => import("./ThreeDimensionalGraphRenderer").then((module) => ({ default: module.ThreeDimensionalGraphRenderer })));
const GRAPH_LIMITS = {
  "2d": { nodes: 100, edges: 250 },
  "3d": { nodes: 40, edges: 80 }
} as const;

export function ScanGraphView({ scan }: { scan: Scan }) {
  const [searchParams, setSearchParams] = useSearchParams();
  const [searchText, setSearchText] = useState("");
  const [rendererError, setRendererError] = useState<Error | null>(null);
  const rendererRef = useRef<GraphRendererHandle | null>(null);
  const settings = useMemo(() => displaySettings(searchParams), [searchParams]);
  const graphQuery = useMemo(() => buildGraphQuery(searchParams), [searchParams]);
  const graph = useQuery({
    queryKey: ["scan-graph", scan.id, graphQuery],
    queryFn: () => getScanGraph(String(scan.id), graphQuery),
    refetchInterval: !isTerminalStatus(scan.status) && searchParams.get("graph_auto_refresh") === "summary" ? 5000 : false,
    placeholderData: (previous) => previous
  });
  const rendererData = useMemo(() => graph.data ? adaptGraphData(graph.data, settings) : null, [graph.data, settings]);
  const selectedNodeId = searchParams.get("selected_node");
  const selectedEdgeId = searchParams.get("selected_edge");
  const selectedNode = rendererData?.nodes.find((node) => node.id === selectedNodeId) ?? null;
  const selectedEdge = rendererData?.links.find((edge) => edge.id === selectedEdgeId) ?? null;
  const occurrenceQuery = selectedEdge ? buildOccurrenceQuery(searchParams) : "";
  const occurrences = useQuery({
    queryKey: ["graph-edge-occurrences", scan.id, selectedEdge?.id, occurrenceQuery],
    queryFn: () => getGraphEdgeOccurrences(String(scan.id), selectedEdge?.id ?? "", occurrenceQuery),
    enabled: Boolean(selectedEdge)
  });
  const searchResults = useMemo(() => {
    if (!rendererData) return [];
    const needle = searchText.trim().toLowerCase();
    if (!needle) return importantNodes(rendererData.nodes);
    return rendererData.nodes
      .filter((node) => [node.label, node.requested_url, node.final_url, node.host, node.path].some((value) => value?.toLowerCase().includes(needle)))
      .slice(0, 30);
  }, [rendererData, searchText]);
  const reducedMotion = useMemo(() => window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false, []);
  const presentation = searchParams.get("presentation") === "1";

  useEffect(() => {
    const limits = GRAPH_LIMITS[settings.mode];
    const maxNodes = boundedNumber(searchParams.get("max_nodes"), limits.nodes, 1, limits.nodes);
    const maxEdges = boundedNumber(searchParams.get("max_edges"), limits.edges, 0, limits.edges);
    if (
      searchParams.get("max_nodes") !== String(maxNodes)
      || searchParams.get("max_edges") !== String(maxEdges)
    ) {
      setSearchParams((current) => {
        const next = new URLSearchParams(current);
        next.set("tab", "graph");
        next.set("max_nodes", String(maxNodes));
        next.set("max_edges", String(maxEdges));
        next.delete("graph_mode");
        return next;
      }, { replace: true });
    }
  }, [searchParams, setSearchParams, settings.mode]);

  useEffect(() => {
    if (selectedNodeId && rendererData && !rendererData.nodes.some((node) => node.id === selectedNodeId)) {
      updateGraphParam(setSearchParams, "selected_node", null);
    }
    if (selectedEdgeId && rendererData && !rendererData.links.some((edge) => edge.id === selectedEdgeId)) {
      updateGraphParam(setSearchParams, "selected_edge", null);
    }
  }, [rendererData, selectedEdgeId, selectedNodeId, setSearchParams]);

  if (graph.error) return <ErrorBanner error={graph.error} title="Could not load graph" />;

  return (
    <div className={presentation ? "fixed inset-0 z-50 overflow-auto bg-stone-950 p-4 text-stone-950" : "space-y-4"}>
      <div className={presentation ? "mx-auto max-w-[1800px] rounded-md bg-stone-50 p-4" : "space-y-4"}>
        <GraphHeader
          scan={scan}
          summary={graph.data?.summary}
          loading={graph.isLoading}
          onRefresh={() => void graph.refetch()}
          presentation={presentation}
          setSearchParams={setSearchParams}
        />
        {graph.data?.summary.truncated ? <TruncationWarning reasons={graph.data.summary.truncation_reasons} /> : null}
        {rendererError ? (
          <div className="rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-950">
            Graph renderer failed: {rendererError.message}. Use the search, node browser, and inspectors below as the accessible fallback.
          </div>
        ) : null}
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-[280px_minmax(0,1fr)_360px]">
          <GraphControls searchParams={searchParams} setSearchParams={setSearchParams} settings={settings} />
          <section className={`min-h-[640px] overflow-hidden rounded-md border border-stone-200 ${settings.background === "dark" ? "bg-stone-950" : "bg-white"} shadow-sm`}>
            {graph.isLoading ? <LoadingBlock label="Loading graph topology..." /> : null}
            {!graph.isLoading && graph.data && graph.data.nodes.length === 0 ? <EmptyState title="No graph nodes" message="This scan has no page snapshots, or current filters removed every page." /> : null}
            {!graph.isLoading && rendererData && rendererData.nodes.length > 0 ? (
              <Suspense fallback={<LoadingBlock label={`Loading ${settings.mode.toUpperCase()} graph renderer...`} />}>
                {settings.mode === "3d" ? (
                  <ThreeDimensionalGraphRenderer
                    ref={rendererRef}
                    data={rendererData}
                    selectedNodeId={selectedNodeId}
                    selectedEdgeId={selectedEdgeId}
                    showLabels={false}
                    showArrows={settings.showArrows}
                    presentation={presentation}
                    reducedMotion={reducedMotion}
                    onNodeSelect={(node) => selectNode(setSearchParams, node)}
                    onEdgeSelect={(edge) => selectEdge(setSearchParams, edge)}
                    onError={setRendererError}
                  />
                ) : (
                  <TwoDimensionalGraphRenderer
                    ref={rendererRef}
                    data={rendererData}
                    selectedNodeId={selectedNodeId}
                    selectedEdgeId={selectedEdgeId}
                    showLabels={labelsVisible(settings, rendererData.nodes.length)}
                    showArrows={settings.showArrows}
                    presentation={presentation}
                    reducedMotion={reducedMotion}
                    onNodeSelect={(node) => selectNode(setSearchParams, node)}
                    onEdgeSelect={(edge) => selectEdge(setSearchParams, edge)}
                    onError={setRendererError}
                  />
                )}
              </Suspense>
            ) : null}
          </section>
          <aside className="space-y-4">
            <GraphActions
              rendererRef={rendererRef}
              selectedNode={selectedNode}
              setSearchParams={setSearchParams}
              presentation={presentation}
            />
            {rendererData ? (
              <NodeBrowser
                searchText={searchText}
                setSearchText={setSearchText}
                nodes={searchResults}
                onSelect={(node) => {
                  selectNode(setSearchParams, node);
                  rendererRef.current?.focusNode(node);
                }}
              />
            ) : null}
            {rendererData ? <EdgeBrowser edges={rendererData.links.slice(0, 20)} onSelect={(edge) => selectEdge(setSearchParams, edge)} /> : null}
            {rendererData ? <Legend data={rendererData} /> : null}
            {selectedNode ? <NodeInspector scanId={String(scan.id)} node={selectedNode} setSearchParams={setSearchParams} /> : null}
            {selectedEdge ? <EdgeInspector scanId={String(scan.id)} edge={selectedEdge} occurrences={occurrences.data} loading={occurrences.isLoading} error={occurrences.error} searchParams={searchParams} setSearchParams={setSearchParams} /> : null}
          </aside>
        </div>
      </div>
    </div>
  );
}

function GraphHeader({ scan, summary, loading, onRefresh, presentation, setSearchParams }: { scan: Scan; summary?: { returned_nodes: number; returned_edges: number; total_available_nodes: number; total_available_edges: number; total_occurrences: number; focused: boolean }; loading: boolean; onRefresh: () => void; presentation: boolean; setSearchParams: ReturnType<typeof useSearchParams>[1] }) {
  return (
    <div className="flex flex-col gap-3 rounded-md border border-stone-200 bg-white p-4 shadow-sm lg:flex-row lg:items-center lg:justify-between">
      <div>
        <h2 className="text-base font-semibold">Website topology graph</h2>
        <p className="mt-1 text-sm text-stone-600">
          {summary ? `${summary.returned_nodes} of ${summary.total_available_nodes} nodes, ${summary.returned_edges} of ${summary.total_available_edges} edges, ${plural(summary.total_occurrences, "stored occurrence")}` : "Graph summary loading"}
          {!isTerminalStatus(scan.status) ? " - scan is still running" : ""}
          {summary?.focused ? " - neighborhood focus active" : ""}
        </p>
      </div>
      <div className="flex flex-wrap gap-2">
        <Button type="button" onClick={onRefresh} loading={loading}>Refresh graph</Button>
        <Button type="button" variant="ghost" onClick={() => updateGraphParam(setSearchParams, "presentation", presentation ? null : "1")}>{presentation ? "Exit presentation" : "Presentation"}</Button>
      </div>
    </div>
  );
}

function GraphControls({ searchParams, setSearchParams, settings }: { searchParams: URLSearchParams; setSearchParams: ReturnType<typeof useSearchParams>[1]; settings: GraphDisplaySettings }) {
  const limits = GRAPH_LIMITS[settings.mode];
  return (
    <aside className="space-y-4 rounded-md border border-stone-200 bg-white p-4 shadow-sm">
      <section className="space-y-3">
        <h3 className="text-sm font-semibold">Data filters</h3>
        <input aria-label="Graph host filter" value={searchParams.get("host") ?? ""} onChange={(event) => updateGraphParam(setSearchParams, "host", event.target.value || null)} placeholder="Host" className={inputClass()} />
        <input aria-label="Graph path prefix" value={searchParams.get("path_prefix") ?? ""} onChange={(event) => updateGraphParam(setSearchParams, "path_prefix", event.target.value || null)} placeholder="/path/" className={inputClass()} />
        <div className="grid grid-cols-2 gap-2">
          <input aria-label="Graph minimum depth" type="number" min={0} value={searchParams.get("min_depth") ?? ""} onChange={(event) => updateGraphParam(setSearchParams, "min_depth", event.target.value || null)} placeholder="Min depth" className={inputClass()} />
          <input aria-label="Graph maximum depth" type="number" min={0} value={searchParams.get("max_depth") ?? ""} onChange={(event) => updateGraphParam(setSearchParams, "max_depth", event.target.value || null)} placeholder="Max depth" className={inputClass()} />
        </div>
        <select aria-label="Graph status filter" value={searchParams.get("graph_status") ?? "any"} onChange={(event) => updateGraphParam(setSearchParams, "graph_status", event.target.value === "any" ? null : event.target.value)} className={inputClass()}>
          <option value="any">All statuses</option><option value="2xx">2xx</option><option value="3xx">3xx</option><option value="4xx">4xx</option><option value="5xx">5xx</option><option value="none">No status</option>
        </select>
        <select aria-label="Graph error filter" value={searchParams.get("error_state") ?? "any"} onChange={(event) => updateGraphParam(setSearchParams, "error_state", event.target.value === "any" ? null : event.target.value)} className={inputClass()}>
          <option value="any">All error states</option><option value="with_errors">Errors only</option><option value="without_errors">No errors</option>
        </select>
        <div className="grid grid-cols-2 gap-2">
          <input aria-label="Minimum inbound links" type="number" min={0} value={searchParams.get("min_inbound") ?? ""} onChange={(event) => updateGraphParam(setSearchParams, "min_inbound", event.target.value || null)} placeholder="Min inbound" className={inputClass()} />
          <input aria-label="Minimum outbound links" type="number" min={0} value={searchParams.get("min_outbound") ?? ""} onChange={(event) => updateGraphParam(setSearchParams, "min_outbound", event.target.value || null)} placeholder="Min outbound" className={inputClass()} />
        </div>
        <div className="grid grid-cols-2 gap-2">
          <input aria-label="Maximum graph nodes" type="number" min={1} max={limits.nodes} value={searchParams.get("max_nodes") ?? String(limits.nodes)} onChange={(event) => updateGraphParam(setSearchParams, "max_nodes", event.target.value || null)} className={inputClass()} />
          <input aria-label="Maximum graph edges" type="number" min={0} max={limits.edges} value={searchParams.get("max_edges") ?? String(limits.edges)} onChange={(event) => updateGraphParam(setSearchParams, "max_edges", event.target.value || null)} className={inputClass()} />
        </div>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={searchParams.get("unfetched") === "1"} onChange={(event) => updateGraphParam(setSearchParams, "unfetched", event.target.checked ? "1" : null)} /> Show unfetched internal pages</label>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={searchParams.get("self_links") !== "0"} onChange={(event) => updateGraphParam(setSearchParams, "self_links", event.target.checked ? null : "0")} /> Show self-links</label>
      </section>
      <section className="space-y-3 border-t border-stone-200 pt-4">
        <h3 className="text-sm font-semibold">Display</h3>
        <select aria-label="Graph mode" value={settings.mode} onChange={(event) => updateGraphParam(setSearchParams, "graph_mode", event.target.value === "2d" ? null : event.target.value, { max_nodes: null, max_edges: null })} className={inputClass()}><option value="2d">2D</option><option value="3d">3D</option></select>
        <select aria-label="Node size" value={settings.sizeBy} onChange={(event) => updateGraphParam(setSearchParams, "size_by", event.target.value)} className={inputClass()}>
          <option value="uniform">Uniform</option><option value="inbound_sources">Unique inbound pages</option><option value="inbound_occurrences">Inbound occurrences</option><option value="outbound_targets">Unique outbound pages</option><option value="outbound_occurrences">Outbound occurrences</option><option value="response_time">Response time</option><option value="depth_inverse">Crawl depth inverse</option>
        </select>
        <select aria-label="Color by" value={settings.colorBy} onChange={(event) => updateGraphParam(setSearchParams, "color_by", event.target.value)} className={inputClass()}>
          <option value="status">HTTP status family</option><option value="fetch_state">Fetch state</option><option value="depth">Crawl depth</option><option value="host">Host</option><option value="path">First path segment</option><option value="error">Error state</option><option value="seed">Seed state</option>
        </select>
        <select aria-label="Graph labels" value={settings.labels} onChange={(event) => updateGraphParam(setSearchParams, "labels", event.target.value)} className={inputClass()}><option value="selected">Selected and important</option><option value="hide">Hide labels</option><option value="important">Important nodes</option><option value="all">All labels for small graphs</option></select>
        <select aria-label="Edge width" value={settings.edgeWidthBy} onChange={(event) => updateGraphParam(setSearchParams, "edge_width", event.target.value)} className={inputClass()}><option value="uniform">Uniform edges</option><option value="occurrences">Occurrence count</option></select>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={settings.showArrows} onChange={(event) => updateGraphParam(setSearchParams, "arrows", event.target.checked ? null : "0")} /> Show arrows</label>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={settings.showIsolated} onChange={(event) => updateGraphParam(setSearchParams, "isolated", event.target.checked ? "1" : null)} /> Show isolated pages</label>
        <select aria-label="Graph background" value={settings.background} onChange={(event) => updateGraphParam(setSearchParams, "background", event.target.value)} className={inputClass()}><option value="light">Light background</option><option value="dark">Dark background</option></select>
        <Button type="button" variant="ghost" onClick={() => setSearchParams(new URLSearchParams({ tab: "graph" }))}>Clear graph state</Button>
      </section>
    </aside>
  );
}

function GraphActions({ rendererRef, selectedNode, setSearchParams, presentation }: { rendererRef: MutableRefObject<GraphRendererHandle | null>; selectedNode: RendererNode | null; setSearchParams: ReturnType<typeof useSearchParams>[1]; presentation: boolean }) {
  async function exportPng() {
    const dataUrl = await rendererRef.current?.exportPng();
    if (!dataUrl) throw new Error("Graph export is unavailable.");
    const link = document.createElement("a");
    link.href = dataUrl;
    link.download = "website-topology-graph.png";
    link.click();
  }
  return (
    <section className="rounded-md border border-stone-200 bg-white p-4 shadow-sm">
      <h3 className="mb-3 text-sm font-semibold">Graph actions</h3>
      <div className="grid grid-cols-2 gap-2">
        <Button type="button" onClick={() => rendererRef.current?.fit()}>Fit</Button>
        <Button type="button" onClick={() => rendererRef.current?.resetCamera()}>Reset camera</Button>
        <Button type="button" onClick={() => rendererRef.current?.freeze()}>Freeze</Button>
        <Button type="button" onClick={() => rendererRef.current?.reheat()}>Reheat</Button>
        <Button type="button" onClick={() => rendererRef.current?.resetLayout()}>Reset layout</Button>
        <Button type="button" onClick={() => void exportPng().catch((error) => window.alert(error instanceof Error ? error.message : "PNG export failed"))}>Export PNG</Button>
      </div>
      {selectedNode?.snapshot_id ? <Button type="button" className="mt-3 w-full" onClick={() => updateGraphParam(setSearchParams, "focus_snapshot_id", String(selectedNode.snapshot_id), { focus_hops: "1" })}>Show neighborhood</Button> : null}
      {presentation ? <p className="mt-3 text-xs text-stone-500">Presentation mode keeps the graph local and uses the current visible layout for export.</p> : null}
    </section>
  );
}

function NodeBrowser({ searchText, setSearchText, nodes, onSelect }: { searchText: string; setSearchText: (value: string) => void; nodes: RendererNode[]; onSelect: (node: RendererNode) => void }) {
  return (
    <section className="rounded-md border border-stone-200 bg-white p-4 shadow-sm">
      <h3 className="mb-3 text-sm font-semibold">Node browser</h3>
      <input aria-label="Search graph nodes" value={searchText} onChange={(event) => setSearchText(event.target.value)} placeholder="Search URL or title" className={inputClass()} />
      <div className="mt-3 max-h-72 overflow-auto divide-y divide-stone-100">
        {nodes.map((node) => (
          <button key={node.id} type="button" onClick={() => onSelect(node)} className="block w-full py-2 text-left text-sm hover:bg-stone-50 focus:outline-none focus:ring-2 focus:ring-neutral-900">
            <span className="block truncate font-medium">{node.label}</span>
            <span className="block truncate font-mono text-xs text-stone-500">{node.requested_url}</span>
          </button>
        ))}
      </div>
    </section>
  );
}

function EdgeBrowser({ edges, onSelect }: { edges: RendererEdge[]; onSelect: (edge: RendererEdge) => void }) {
  return (
    <section className="rounded-md border border-stone-200 bg-white p-4 shadow-sm">
      <h3 className="mb-3 text-sm font-semibold">Edge browser</h3>
      {!edges.length ? <p className="text-sm text-stone-600">No page-to-page edges in the current graph.</p> : null}
      <div className="max-h-56 overflow-auto divide-y divide-stone-100">
        {edges.map((edge) => (
          <button key={edge.id} type="button" onClick={() => onSelect(edge)} className="block w-full py-2 text-left text-sm hover:bg-stone-50 focus:outline-none focus:ring-2 focus:ring-neutral-900">
            <span className="block font-medium">{edge.label}</span>
            <span className="block text-xs text-stone-500">snapshot {edge.source_snapshot_id} to {edge.target_snapshot_id ?? `resource ${edge.target_resource_id}`}</span>
          </button>
        ))}
      </div>
    </section>
  );
}

function Legend({ data }: { data: { legend: Array<{ key: string; label: string; color: string }>; sizeLegend: string } }) {
  return (
    <section className="rounded-md border border-stone-200 bg-white p-4 text-sm shadow-sm">
      <h3 className="mb-2 font-semibold">Legend</h3>
      <p className="mb-2 text-xs text-stone-500">{data.sizeLegend}</p>
      <div className="space-y-1">
        {data.legend.map((item) => <div key={item.key} className="flex items-center gap-2"><span className="size-3 rounded-full" style={{ backgroundColor: item.color }} />{item.label}</div>)}
      </div>
    </section>
  );
}

function NodeInspector({ scanId, node, setSearchParams }: { scanId: string; node: RendererNode; setSearchParams: ReturnType<typeof useSearchParams>[1] }) {
  return (
    <section className="rounded-md border border-stone-200 bg-white p-4 text-sm shadow-sm">
      <h3 className="mb-2 font-semibold">Selected page</h3>
      <div className="space-y-1">
        <div className="font-medium">{node.label}</div>
        <div className="break-all font-mono text-xs text-stone-600">{node.requested_url}</div>
        <div>Kind: {node.kind}</div><div>Category: {node.categoryLabel}</div><div>Depth: {node.crawl_depth ?? "Unknown"}</div><div>Status: {node.http_status ?? formatStatus(node.fetch_state ?? "unknown")}</div>
        <div>Inbound: {node.inbound_occurrence_count} occurrences from {node.inbound_source_page_count} pages</div>
        <div>Outbound: {node.outbound_occurrence_count} occurrences to {node.outbound_target_page_count} pages</div>
        {node.error_type ? <div>Error: {formatStatus(node.error_type)}</div> : null}
      </div>
      <div className="mt-3 flex flex-wrap gap-2">
        {node.snapshot_id ? <Link className="rounded-md border border-stone-300 bg-white px-3 py-2 text-sm font-medium" to={`/scans/${scanId}/pages/${node.snapshot_id}`}>Open details</Link> : null}
        {node.snapshot_id ? <Link className="rounded-md border border-stone-300 bg-white px-3 py-2 text-sm font-medium" to={`/scans/${scanId}/pages/${node.snapshot_id}?tab=inbound`}>Inbound</Link> : null}
        {node.snapshot_id ? <Link className="rounded-md border border-stone-300 bg-white px-3 py-2 text-sm font-medium" to={`/scans/${scanId}/pages/${node.snapshot_id}?tab=links`}>Outgoing</Link> : null}
        {node.final_url || node.requested_url ? <a className="rounded-md border border-stone-300 bg-white px-3 py-2 text-sm font-medium" href={node.final_url ?? node.requested_url ?? "#"} target="_blank" rel="noreferrer">Open live URL</a> : null}
        {node.snapshot_id ? <Button type="button" onClick={() => updateGraphParam(setSearchParams, "focus_snapshot_id", String(node.snapshot_id), { focus_hops: "1" })}>Neighborhood</Button> : null}
      </div>
    </section>
  );
}

function EdgeInspector({ scanId, edge, occurrences, loading, error, searchParams, setSearchParams }: { scanId: string; edge: RendererEdge; occurrences?: { items: Array<{ id: number; anchor_text: string | null; raw_href: string | null; dom_path: string | null; rel: string | null; scope_decision: string; discovered_at: string }>; total: number; limit: number; offset: number }; loading: boolean; error: unknown; searchParams: URLSearchParams; setSearchParams: ReturnType<typeof useSearchParams>[1] }) {
  const search = searchParams.get("edge_search") ?? "";
  return (
    <section className="rounded-md border border-stone-200 bg-white p-4 text-sm shadow-sm">
      <h3 className="mb-2 font-semibold">Selected edge</h3>
      <p>{edge.occurrence_count} stored occurrences, {edge.nofollow_occurrence_count} nofollow, {edge.empty_anchor_occurrence_count} empty anchors.</p>
      <p className="mt-1 text-xs text-stone-500">First seen {formatDate(edge.first_discovered_at)}. Last seen {formatDate(edge.last_discovered_at)}.</p>
      <div className="mt-3 flex flex-wrap gap-2">
        <Link className="rounded-md border border-stone-300 bg-white px-3 py-2 text-sm font-medium" to={`/scans/${scanId}/pages/${edge.source_snapshot_id}`}>Source page</Link>
        {edge.target_snapshot_id ? <Link className="rounded-md border border-stone-300 bg-white px-3 py-2 text-sm font-medium" to={`/scans/${scanId}/pages/${edge.target_snapshot_id}`}>Target page</Link> : null}
      </div>
      <input aria-label="Search edge occurrences" value={search} onChange={(event) => updateGraphParam(setSearchParams, "edge_search", event.target.value || null, { edge_offset: null })} placeholder="Search occurrences" className={`${inputClass()} mt-3`} />
      {error ? <ErrorBanner error={error} title="Could not load edge occurrences" /> : null}
      {loading ? <LoadingBlock label="Loading edge occurrences..." /> : null}
      <div className="mt-3 max-h-72 overflow-auto divide-y divide-stone-100">
        {(occurrences?.items ?? []).map((item) => (
          <div key={item.id} className="py-2 text-xs">
            <div className="font-medium">{item.anchor_text || "Empty anchor"}</div>
            <div className="break-all font-mono text-stone-600">{item.raw_href}</div>
            <div className="text-stone-500">{item.scope_decision}{item.rel ? ` - rel=${item.rel}` : ""}{item.dom_path ? ` - ${item.dom_path}` : ""}</div>
          </div>
        ))}
      </div>
    </section>
  );
}

function TruncationWarning({ reasons }: { reasons: string[] }) {
  return <div className="rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-950">Graph data was limited: {reasons.join(", ")}. Increase limits or use neighborhood focus for a smaller deterministic view.</div>;
}

function buildGraphQuery(searchParams: URLSearchParams) {
  const params = new URLSearchParams();
  for (const [sourceKey, targetKey = sourceKey] of [["max_nodes"], ["max_edges"], ["min_depth"], ["max_depth"], ["host"], ["path_prefix"], ["fetch_state"], ["error_state"], ["min_inbound"], ["min_outbound"], ["focus_snapshot_id"], ["focus_hops"], ["graph_status", "status"]] as Array<[string, string?]>) {
    const value = searchParams.get(sourceKey);
    if (value) params.set(targetKey, value);
  }
  const mode = graphMode(searchParams);
  const limits = GRAPH_LIMITS[mode];
  params.set("max_nodes", String(boundedNumber(params.get("max_nodes"), limits.nodes, 1, limits.nodes)));
  params.set("max_edges", String(boundedNumber(params.get("max_edges"), limits.edges, 0, limits.edges)));
  params.set("include_self_links", searchParams.get("self_links") === "0" ? "false" : "true");
  params.set("include_unfetched", searchParams.get("unfetched") === "1" ? "true" : "false");
  return `?${params.toString()}`;
}

function buildOccurrenceQuery(searchParams: URLSearchParams) {
  const params = new URLSearchParams();
  const search = searchParams.get("edge_search");
  if (search) params.set("search", search);
  const offset = searchParams.get("edge_offset");
  if (offset) params.set("offset", offset);
  return `?${params.toString()}`;
}

function displaySettings(searchParams: URLSearchParams): GraphDisplaySettings {
  return {
    mode: graphMode(searchParams),
    sizeBy: (searchParams.get("size_by") as GraphDisplaySettings["sizeBy"]) || "uniform",
    colorBy: (searchParams.get("color_by") as GraphDisplaySettings["colorBy"]) || "status",
    labels: (searchParams.get("labels") as GraphDisplaySettings["labels"]) || "selected",
    edgeWidthBy: (searchParams.get("edge_width") as GraphDisplaySettings["edgeWidthBy"]) || "occurrences",
    showArrows: searchParams.get("arrows") !== "0",
    showIsolated: searchParams.get("isolated") === "1",
    background: searchParams.get("background") === "dark" ? "dark" : "light"
  };
}

function graphMode(searchParams: URLSearchParams): GraphDisplaySettings["mode"] {
  return searchParams.get("graph_mode") === "3d" ? "3d" : "2d";
}

function boundedNumber(value: string | null, fallback: number, min: number, max: number) {
  if (!value?.trim()) return fallback;
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.min(max, Math.max(min, Math.trunc(parsed)));
}

function labelsVisible(settings: GraphDisplaySettings, nodeCount: number) {
  if (settings.labels === "hide") return false;
  if (settings.labels === "all") return nodeCount <= 150;
  return settings.labels === "important" || settings.labels === "selected";
}

function importantNodes(nodes: RendererNode[]) {
  return [...nodes]
    .sort((left, right) => Number(right.is_starting_url) - Number(left.is_starting_url) || Number(right.is_scan_seed) - Number(left.is_scan_seed) || right.inbound_source_page_count - left.inbound_source_page_count || Number(Boolean(right.error_type)) - Number(Boolean(left.error_type)))
    .slice(0, 20);
}

function selectNode(setSearchParams: ReturnType<typeof useSearchParams>[1], node: RendererNode) {
  updateGraphParam(setSearchParams, "selected_node", node.id, { selected_edge: null });
}

function selectEdge(setSearchParams: ReturnType<typeof useSearchParams>[1], edge: RendererEdge | GraphEdge) {
  updateGraphParam(setSearchParams, "selected_edge", edge.id, { selected_node: null, edge_offset: null });
}

function updateGraphParam(setSearchParams: ReturnType<typeof useSearchParams>[1], key: string, value: string | null, resets: Record<string, string | null> = {}) {
  setSearchParams((current) => {
    const next = new URLSearchParams(current);
    next.set("tab", "graph");
    if (value) next.set(key, value);
    else next.delete(key);
    for (const [resetKey, resetValue] of Object.entries(resets)) {
      if (resetValue) next.set(resetKey, resetValue);
      else next.delete(resetKey);
    }
    return next;
  });
}
