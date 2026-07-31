import type { RendererEdge, RendererGraphData, RendererNode } from "./graphDataAdapter";

export type GraphRendererHandle = {
  fit: () => void;
  resetCamera: () => void;
  focusNode: (node: RendererNode) => void;
  freeze: () => void;
  reheat: () => void;
  resetLayout: () => void;
  exportPng: () => Promise<string>;
};

export type GraphRendererProps = {
  data: RendererGraphData;
  selectedNodeId: string | null;
  selectedEdgeId: string | null;
  showLabels: boolean;
  showArrows: boolean;
  presentation: boolean;
  reducedMotion: boolean;
  onNodeSelect: (node: RendererNode) => void;
  onEdgeSelect: (edge: RendererEdge) => void;
  onError: (error: Error) => void;
};
