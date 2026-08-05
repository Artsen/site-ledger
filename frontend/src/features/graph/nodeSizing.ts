import type { GraphNode, GraphSizeBy } from "../../types/graph";

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

export function sizeLabel(sizeBy: GraphSizeBy) {
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
