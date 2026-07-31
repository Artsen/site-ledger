import type { GraphColorBy, GraphDisplaySettings, GraphEdge, GraphNode, GraphResponse, GraphSizeBy } from "../../types/graph";

export type RendererNode = GraphNode & {
  x: number;
  y: number;
  z: number;
  val: number;
  color: string;
  label: string;
  categoryLabel: string;
};

export type RendererEdge = GraphEdge & {
  source: string;
  target: string;
  width: number;
  color: string;
  label: string;
};

export type RendererGraphData = {
  nodes: RendererNode[];
  links: RendererEdge[];
  legend: Array<{ key: string; label: string; color: string }>;
  sizeLegend: string;
};

const palette = ["#2563eb", "#059669", "#d97706", "#7c3aed", "#dc2626", "#0891b2", "#4b5563", "#be123c", "#65a30d", "#9333ea"];

export function adaptGraphData(graph: GraphResponse, settings: GraphDisplaySettings): RendererGraphData {
  const nodes = graph.nodes.map((node) => {
    const coordinates = deterministicCoordinates(node.id);
    const category = categoryForNode(node, settings.colorBy);
    return {
      ...node,
      ...coordinates,
      val: nodeSize(node, settings.sizeBy),
      color: category.color,
      label: nodeLabel(node),
      categoryLabel: category.label
    };
  });
  const edges = graph.edges.map((edge) => ({
    ...edge,
    width: edgeWidth(edge, settings.edgeWidthBy),
    color: edge.is_self_link ? "rgba(120, 113, 108, 0.45)" : "rgba(68, 64, 60, 0.45)",
    label: `${edge.occurrence_count} ${edge.occurrence_count === 1 ? "link" : "links"}`
  }));
  return {
    nodes,
    links: edges,
    legend: legendFor(graph.nodes, settings.colorBy),
    sizeLegend: sizeLabel(settings.sizeBy)
  };
}

export function deterministicCoordinates(id: string) {
  const first = stableHash(`${id}:x`);
  const second = stableHash(`${id}:y`);
  const third = stableHash(`${id}:z`);
  return {
    x: scaleHash(first, 420),
    y: scaleHash(second, 420),
    z: scaleHash(third, 260)
  };
}

export function nodeSize(node: GraphNode, sizeBy: GraphSizeBy) {
  const raw = (() => {
    switch (sizeBy) {
      case "inbound_sources":
        return node.inbound_source_page_count;
      case "inbound_occurrences":
        return node.inbound_occurrence_count;
      case "outbound_targets":
        return node.outbound_target_page_count;
      case "outbound_occurrences":
        return node.outbound_occurrence_count;
      case "response_time":
        return node.response_time_ms ?? 0;
      case "depth_inverse":
        return Math.max(0, 8 - (node.crawl_depth ?? 8));
      default:
        return 1;
    }
  })();
  if (sizeBy === "uniform") return 5;
  return Math.max(3, Math.min(16, 3 + Math.sqrt(Math.max(0, raw)) * 2.2));
}

export function edgeWidth(edge: GraphEdge, edgeWidthBy: GraphDisplaySettings["edgeWidthBy"]) {
  if (edgeWidthBy === "uniform") return 1.2;
  return Math.max(1, Math.min(6, 1 + Math.sqrt(edge.occurrence_count)));
}

export function categoryForNode(node: GraphNode, colorBy: GraphColorBy) {
  const label = categoryKey(node, colorBy);
  return { label, color: palette[Math.abs(stableHash(label)) % palette.length] };
}

export function nodeLabel(node: GraphNode) {
  if (node.page_title?.trim()) return node.page_title.trim();
  if (node.path) return node.path;
  return node.requested_url ?? node.id;
}

function legendFor(nodes: GraphNode[], colorBy: GraphColorBy) {
  const keys = Array.from(new Set(nodes.map((node) => categoryKey(node, colorBy)))).slice(0, palette.length);
  return keys.map((key) => ({ key, label: key, color: palette[Math.abs(stableHash(key)) % palette.length] }));
}

function categoryKey(node: GraphNode, colorBy: GraphColorBy) {
  if (node.kind === "discovered") return "Discovered";
  switch (colorBy) {
    case "fetch_state":
      return node.fetch_state ?? "Unknown fetch state";
    case "depth":
      return node.crawl_depth == null ? "Depth unknown" : `Depth ${node.crawl_depth}`;
    case "host":
      return node.host ?? "Host unknown";
    case "path":
      return firstPathSegment(node.path);
    case "error":
      return node.error_type ?? "No crawler error";
    case "seed":
      return node.is_scan_seed ? "Scan seed" : "Discovered by crawl";
    default:
      if (node.error_type) return "Crawler error";
      if (node.http_status == null) return "No HTTP status";
      return `${Math.floor(node.http_status / 100)}xx`;
  }
}

function firstPathSegment(path: string | null) {
  if (!path || path === "/") return "/";
  return `/${path.split("/").filter(Boolean)[0]}/`;
}

function sizeLabel(sizeBy: GraphSizeBy) {
  const labels: Record<GraphSizeBy, string> = {
    uniform: "Uniform node size",
    inbound_sources: "Node size: unique inbound pages",
    inbound_occurrences: "Node size: inbound occurrences",
    outbound_targets: "Node size: unique outbound pages",
    outbound_occurrences: "Node size: outbound occurrences",
    response_time: "Node size: response time",
    depth_inverse: "Node size: shallow pages larger"
  };
  return labels[sizeBy];
}

function stableHash(value: string) {
  let hash = 2166136261;
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return hash >>> 0;
}

function scaleHash(hash: number, radius: number) {
  return (hash / 0xffffffff - 0.5) * radius;
}
