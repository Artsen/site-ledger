import type { GraphColorBy, GraphNode } from "../../types/graph";
import { stableHash } from "./coordinates";

const palette = ["#2563eb", "#059669", "#d97706", "#7c3aed", "#dc2626", "#0891b2", "#4b5563", "#be123c", "#65a30d", "#9333ea"];

export function categoryForNode(node: GraphNode, colorBy: GraphColorBy) {
  const label = categoryKey(node, colorBy);
  return { label, color: palette[Math.abs(stableHash(label)) % palette.length] };
}

export function nodeLabel(node: GraphNode) {
  if (node.page_title?.trim()) return node.page_title.trim();
  if (node.path) return node.path;
  return node.requested_url ?? node.id;
}

export function legendFor(nodes: GraphNode[], colorBy: GraphColorBy) {
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
