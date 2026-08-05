import type { GraphEdge, GraphNode } from "../../types/graph";

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
