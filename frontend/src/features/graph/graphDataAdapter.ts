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
  displayKind: "hierarchy" | "page_link";
  linkCategory: "hierarchy" | "content" | "navigation" | "template";
  selectable: boolean;
};

export type RendererGraphData = {
  nodes: RendererNode[];
  links: RendererEdge[];
  legend: Array<{ key: string; label: string; color: string }>;
  sizeLegend: string;
};

const palette = ["#2563eb", "#059669", "#d97706", "#7c3aed", "#dc2626", "#0891b2", "#4b5563", "#be123c", "#65a30d", "#9333ea"];

export function adaptGraphData(graph: GraphResponse, settings: GraphDisplaySettings, selectedNodeId: string | null = null, selectedEdgeId: string | null = null): RendererGraphData {
  const connectedNodeIds = new Set(graph.edges.flatMap((edge) => [edge.source, edge.target]));
  const visibleNodes = settings.showIsolated
    ? graph.nodes
    : graph.nodes.filter((node) => connectedNodeIds.has(node.id) || node.is_starting_url);
  const visibleNodeIds = new Set(visibleNodes.map((node) => node.id));
  const layout = urlHierarchyLayout(visibleNodes);
  const nodes = visibleNodes.map((node) => {
    const coordinates = layout.coordinates.get(node.id) ?? deterministicCoordinates(node.id);
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
  const hierarchyEdges = hierarchyRendererEdges(nodes, layout.parentByNodeId);
  const nodeById = new Map(nodes.map((node) => [node.id, node]));
  const pageLinkEdges = graph.edges
    .filter((edge) => visibleNodeIds.has(edge.source) && visibleNodeIds.has(edge.target))
    .filter((edge) => shouldDisplayPageLink(edge, settings, selectedNodeId, selectedEdgeId, nodeById, graph.summary.fetched_nodes))
    .map((edge) => ({
      ...edge,
      width: edgeWidth(edge, settings.edgeWidthBy),
      color: edge.is_self_link ? "rgba(120, 113, 108, 0.22)" : "rgba(68, 64, 60, 0.24)",
      label: `${edge.occurrence_count} ${edge.occurrence_count === 1 ? "link" : "links"}`,
      displayKind: "page_link" as const,
      linkCategory: linkCategory(edge, nodeById.get(edge.target), graph.summary.fetched_nodes),
      selectable: true
    }));
  return {
    nodes,
    links: [...hierarchyEdges, ...pageLinkEdges],
    legend: legendFor(visibleNodes, settings.colorBy),
    sizeLegend: sizeLabel(settings.sizeBy)
  };
}

export function deterministicCoordinates(id: string) {
  const angle = unitHash(`${id}:angle`) * Math.PI * 2;
  const radius = Math.sqrt(unitHash(`${id}:radius`)) * 420;
  const depthAngle = unitHash(`${id}:depth`) * Math.PI * 2;
  const depthRadius = Math.sqrt(unitHash(`${id}:depth-radius`)) * 260;
  return {
    x: Math.cos(angle) * radius,
    y: Math.sin(angle) * radius,
    z: Math.sin(depthAngle) * depthRadius
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

function urlHierarchyLayout(nodes: GraphNode[]) {
  const nodeInfo = nodes.map((node) => ({ node, parts: nodeUrlParts(node) }));
  const pathNodeByHost = new Map<string, Map<string, GraphNode>>();
  for (const { node, parts } of nodeInfo) {
    const hostMap = pathNodeByHost.get(parts.host) ?? new Map<string, GraphNode>();
    if (!pathNodeByHost.has(parts.host)) pathNodeByHost.set(parts.host, hostMap);
    const key = pathKey(parts.path);
    if (!hostMap.has(key)) hostMap.set(key, node);
  }

  const parentByNodeId = new Map<string, string>();
  for (const { node, parts } of nodeInfo) {
    const parent = closestParentNode(parts.host, parts.path, node.id, pathNodeByHost);
    if (parent) parentByNodeId.set(node.id, parent.id);
  }

  const hosts = Array.from(new Set(nodeInfo.map((item) => item.parts.host))).sort((left, right) => {
    const leftStart = nodeInfo.some((item) => item.parts.host === left && item.node.is_starting_url);
    const rightStart = nodeInfo.some((item) => item.parts.host === right && item.node.is_starting_url);
    return Number(rightStart) - Number(leftStart) || left.localeCompare(right);
  });

  const coordinates = new Map<string, { x: number; y: number; z: number }>();
  let hostOffset = 0;
  for (const host of hosts) {
    const hostItems = nodeInfo
      .filter((item) => item.parts.host === host)
      .sort((left, right) => left.parts.path.localeCompare(right.parts.path) || left.node.id.localeCompare(right.node.id));
    const childrenByParent = new Map<string | null, GraphNode[]>();
    for (const { node } of hostItems) {
      const parentId = parentByNodeId.get(node.id) ?? null;
      const siblings = childrenByParent.get(parentId) ?? [];
      siblings.push(node);
      childrenByParent.set(parentId, siblings);
    }
    for (const siblings of childrenByParent.values()) {
      siblings.sort((left, right) => nodePath(left).localeCompare(nodePath(right)) || left.id.localeCompare(right.id));
    }

    let row = 0;
    const roots = childrenByParent.get(null) ?? [];
    const place = (node: GraphNode, level: number): number => {
      const children = childrenByParent.get(node.id) ?? [];
      if (!children.length) {
        coordinates.set(node.id, { x: hostOffset + level * 190, y: row * 54, z: level * 44 });
        row += 1;
        return coordinates.get(node.id)?.y ?? 0;
      }
      const childRows: number[] = children.map((child) => place(child, level + 1));
      const y: number = (Math.min(...childRows) + Math.max(...childRows)) / 2;
      coordinates.set(node.id, { x: hostOffset + level * 190, y, z: level * 44 });
      return y;
    };

    for (const root of roots) place(root, pathDepth(nodePath(root)));
    const maxLevel = Math.max(0, ...hostItems.map((item) => pathDepth(item.parts.path)));
    const chartWidth = Math.max(420, (maxLevel + 2) * 190);
    hostOffset += chartWidth + 260;
  }

  centerCoordinates(coordinates);
  return { coordinates, parentByNodeId };
}

function hierarchyRendererEdges(nodes: RendererNode[], parentByNodeId: Map<string, string>): RendererEdge[] {
  const nodeById = new Map(nodes.map((node) => [node.id, node]));
  return Array.from(parentByNodeId.entries()).flatMap(([childId, parentId]) => {
    const parent = nodeById.get(parentId);
    const child = nodeById.get(childId);
    if (!parent || !child) return [];
    const parentSnapshotId = snapshotIdFromNode(parent);
    const childSnapshotId = snapshotIdFromNode(child);
    return [{
      id: `hierarchy:${parentId}->${childId}`,
      source: parentId,
      target: childId,
      source_snapshot_id: parentSnapshotId ?? 0,
      target_snapshot_id: childSnapshotId,
      target_resource_id: child.resource_id,
      occurrence_count: 1,
      unique_anchor_text_count: 0,
      nofollow_occurrence_count: 0,
      follow_occurrence_count: 0,
      empty_anchor_occurrence_count: 0,
      is_self_link: false,
      sample_anchor_texts: [],
      first_discovered_at: null,
      last_discovered_at: null,
      scope_decisions: {},
      dom_regions: {},
      width: 1.4,
      color: "rgba(37, 99, 235, 0.55)",
      label: "URL parent-child",
      displayKind: "hierarchy" as const,
      linkCategory: "hierarchy" as const,
      selectable: false
    }];
  });
}

function shouldDisplayPageLink(edge: GraphEdge, settings: GraphDisplaySettings, selectedNodeId: string | null, selectedEdgeId: string | null, nodeById: Map<string, GraphNode>, fetchedNodeCount: number) {
  if (settings.linkVisibility === "hidden") return false;
  if (selectedEdgeId === edge.id) return true;
  if (settings.linkVisibility === "selected" && selectedNodeId && edge.source !== selectedNodeId && edge.target !== selectedNodeId) return false;
  if (settings.linkVisibility === "selected" && !selectedNodeId) return false;
  const category = linkCategory(edge, nodeById.get(edge.target), fetchedNodeCount);
  return settings.linkCategoryFilter === "all" || settings.linkCategoryFilter === category;
}

function linkCategory(edge: GraphEdge, target: GraphNode | undefined, fetchedNodeCount: number): RendererEdge["linkCategory"] {
  if (hasDomRegion(edge, ["header", "footer", "nav", "aside"])) return "navigation";
  const sourceCoverage = target && fetchedNodeCount > 0 ? target.inbound_source_page_count / fetchedNodeCount : 0;
  if ((target?.inbound_source_page_count ?? 0) >= 3 && sourceCoverage >= 0.45) return "template";
  return "content";
}

function hasDomRegion(edge: GraphEdge, regions: string[]) {
  return regions.some((region) => (edge.dom_regions[region] ?? 0) > 0);
}

function closestParentNode(host: string, path: string, nodeId: string, pathNodeByHost: Map<string, Map<string, GraphNode>>) {
  const hostMap = pathNodeByHost.get(host);
  if (!hostMap) return null;
  const parts = path.split("/").filter(Boolean);
  for (let length = parts.length - 1; length >= 0; length -= 1) {
    const candidatePath = length === 0 ? "/" : `/${parts.slice(0, length).join("/")}/`;
    const candidate = hostMap.get(pathKey(candidatePath)) ?? hostMap.get(pathKey(candidatePath.replace(/\/$/, "")));
    if (candidate && candidate.id !== nodeId) return candidate;
  }
  return null;
}

function nodeUrlParts(node: GraphNode) {
  const parsed = parseNodeUrl(node);
  return {
    host: node.host || parsed?.host || "Unknown host",
    path: node.path || parsed?.pathname || "/"
  };
}

function parseNodeUrl(node: GraphNode) {
  const value = node.final_url || node.requested_url;
  if (!value) return null;
  try {
    return new URL(value);
  } catch {
    return null;
  }
}

function nodePath(node: GraphNode) {
  return nodeUrlParts(node).path;
}

function pathKey(path: string) {
  if (!path) return "/";
  return path === "/" ? "/" : path.replace(/\/$/, "");
}

function pathDepth(path: string) {
  if (!path || path === "/") return 0;
  return path.split("/").filter(Boolean).length;
}

function snapshotIdFromNode(node: GraphNode) {
  if (node.snapshot_id) return node.snapshot_id;
  const match = /^snapshot:(\d+)$/.exec(node.id);
  return match ? Number(match[1]) : null;
}

function centerCoordinates(coordinates: Map<string, { x: number; y: number; z: number }>) {
  if (!coordinates.size) return;
  const values = Array.from(coordinates.values());
  const minX = Math.min(...values.map((item) => item.x));
  const maxX = Math.max(...values.map((item) => item.x));
  const minY = Math.min(...values.map((item) => item.y));
  const maxY = Math.max(...values.map((item) => item.y));
  const shiftX = (minX + maxX) / 2;
  const shiftY = (minY + maxY) / 2;
  for (const value of values) {
    value.x -= shiftX;
    value.y -= shiftY;
  }
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

function unitHash(value: string) {
  return mixHash(stableHash(value)) / 0xffffffff;
}

function mixHash(value: number) {
  let hash = value >>> 0;
  hash ^= hash >>> 16;
  hash = Math.imul(hash, 0x7feb352d);
  hash ^= hash >>> 15;
  hash = Math.imul(hash, 0x846ca68b);
  hash ^= hash >>> 16;
  return hash >>> 0;
}
