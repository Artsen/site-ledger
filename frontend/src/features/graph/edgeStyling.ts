import type { GraphDisplaySettings, GraphEdge } from "../../types/graph";

export function edgeWidth(edge: GraphEdge, edgeWidthBy: GraphDisplaySettings["edgeWidthBy"]) {
  if (edgeWidthBy === "uniform") return 1.2;
  return Math.max(1, Math.min(6, 1 + Math.sqrt(edge.occurrence_count)));
}
