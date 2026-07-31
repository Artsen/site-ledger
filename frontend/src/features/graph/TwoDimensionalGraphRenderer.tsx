import { forwardRef, useEffect, useImperativeHandle, useMemo, useRef } from "react";
import ForceGraph2D from "react-force-graph-2d";

import type { GraphRendererHandle, GraphRendererProps } from "./GraphRendererTypes";
import { deterministicCoordinates, type RendererEdge, type RendererNode } from "./graphDataAdapter";

type ForceGraphRef = {
  zoomToFit?: (duration?: number, padding?: number) => void;
  centerAt?: (x?: number, y?: number, duration?: number) => void;
  zoom?: (zoom?: number, duration?: number) => void;
  pauseAnimation?: () => void;
  resumeAnimation?: () => void;
  d3ReheatSimulation?: () => void;
  canvas?: () => HTMLCanvasElement;
};

export const TwoDimensionalGraphRenderer = forwardRef<GraphRendererHandle, GraphRendererProps>(function TwoDimensionalGraphRenderer(
  { data, selectedNodeId, selectedEdgeId, showLabels, showArrows, presentation, reducedMotion, onNodeSelect, onEdgeSelect, onError },
  ref
) {
  const graphRef = useRef<ForceGraphRef | null>(null);
  const graphData = useMemo(() => ({ nodes: data.nodes.map((node) => ({ ...node })), links: data.links.map((link) => ({ ...link })) }), [data]);

  useEffect(() => {
    window.setTimeout(() => graphRef.current?.zoomToFit?.(reducedMotion ? 0 : 450, 48), 80);
    const timer = window.setTimeout(() => graphRef.current?.pauseAnimation?.(), reducedMotion ? 500 : 5500);
    return () => window.clearTimeout(timer);
  }, [graphData, reducedMotion]);

  useImperativeHandle(ref, () => ({
    fit: () => graphRef.current?.zoomToFit?.(reducedMotion ? 0 : 450, 48),
    resetCamera: () => {
      graphRef.current?.centerAt?.(0, 0, reducedMotion ? 0 : 300);
      graphRef.current?.zoom?.(1, reducedMotion ? 0 : 300);
    },
    focusNode: (node) => {
      graphRef.current?.centerAt?.(node.x, node.y, reducedMotion ? 0 : 450);
      graphRef.current?.zoom?.(3, reducedMotion ? 0 : 450);
    },
    freeze: () => graphRef.current?.pauseAnimation?.(),
    reheat: () => {
      graphRef.current?.resumeAnimation?.();
      graphRef.current?.d3ReheatSimulation?.();
    },
    resetLayout: () => {
      for (const node of graphData.nodes) {
        const position = deterministicCoordinates(node.id);
        node.x = position.x;
        node.y = position.y;
        node.z = 0;
        Object.assign(node, { vx: 0, vy: 0 });
      }
      graphRef.current?.d3ReheatSimulation?.();
      graphRef.current?.zoomToFit?.(reducedMotion ? 0 : 450, 48);
    },
    exportPng: async () => {
      const canvas = graphRef.current?.canvas?.();
      if (!canvas) throw new Error("Graph canvas is not available.");
      return canvas.toDataURL("image/png");
    }
  }), [graphData.nodes, reducedMotion]);

  try {
    return (
      <div className="h-full min-h-[560px]" aria-label="2D website topology graph canvas">
        <ForceGraph2D
          ref={graphRef as never}
          graphData={graphData}
          nodeId="id"
          nodeLabel={(node: RendererNode) => node.label}
          nodeVal={(node: RendererNode) => node.val}
          nodeColor={(node: RendererNode) => selectedNodeId === node.id ? "#111827" : node.color}
          linkWidth={(link: RendererEdge) => selectedEdgeId === link.id ? Math.max(3, link.width + 1) : link.width}
          linkColor={(link: RendererEdge) => selectedEdgeId === link.id ? "rgba(17,24,39,0.85)" : link.color}
          linkDirectionalArrowLength={showArrows ? 5 : 0}
          linkDirectionalArrowRelPos={1}
          cooldownTicks={reducedMotion ? 20 : 100}
          backgroundColor={presentation ? "#fafaf9" : "#ffffff"}
          onNodeClick={(node: RendererNode) => onNodeSelect(node)}
          onLinkClick={(link: RendererEdge) => onEdgeSelect(link)}
          nodeCanvasObjectMode={() => (showLabels ? "after" : undefined)}
          nodeCanvasObject={(node: RendererNode, context, globalScale) => {
            if (!showLabels) return;
            const fontSize = Math.max(3, 12 / globalScale);
            context.font = `${fontSize}px Inter, system-ui, sans-serif`;
            context.fillStyle = selectedNodeId === node.id ? "#111827" : "#44403c";
            context.fillText(node.label.slice(0, 80), (node.x ?? 0) + 7, (node.y ?? 0) + 3);
          }}
        />
      </div>
    );
  } catch (error) {
    onError(error instanceof Error ? error : new Error("2D graph renderer failed."));
    return null;
  }
});
