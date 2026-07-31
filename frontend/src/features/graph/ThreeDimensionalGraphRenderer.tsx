import { forwardRef, useEffect, useImperativeHandle, useMemo, useRef } from "react";
import ForceGraph3D from "react-force-graph-3d";

import type { GraphRendererHandle, GraphRendererProps } from "./GraphRendererTypes";
import { deterministicCoordinates, type RendererEdge, type RendererNode } from "./graphDataAdapter";

type ForceGraph3DRef = {
  zoomToFit?: (duration?: number, padding?: number) => void;
  cameraPosition?: (position?: { x: number; y: number; z: number }, lookAt?: { x: number; y: number; z: number }, duration?: number) => void;
  pauseAnimation?: () => void;
  resumeAnimation?: () => void;
  d3ReheatSimulation?: () => void;
};

export const ThreeDimensionalGraphRenderer = forwardRef<GraphRendererHandle, GraphRendererProps>(function ThreeDimensionalGraphRenderer(
  { data, selectedNodeId, selectedEdgeId, showLabels, showArrows, presentation, reducedMotion, onNodeSelect, onEdgeSelect, onError },
  ref
) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const graphRef = useRef<ForceGraph3DRef | null>(null);
  const graphData = useMemo(() => ({ nodes: data.nodes.map((node) => ({ ...node })), links: data.links.map((link) => ({ ...link })) }), [data]);

  useEffect(() => {
    window.setTimeout(() => graphRef.current?.zoomToFit?.(reducedMotion ? 0 : 500, 80), 120);
    const timer = window.setTimeout(() => graphRef.current?.pauseAnimation?.(), reducedMotion ? 700 : 6500);
    return () => window.clearTimeout(timer);
  }, [graphData, reducedMotion]);

  useImperativeHandle(ref, () => ({
    fit: () => graphRef.current?.zoomToFit?.(reducedMotion ? 0 : 500, 80),
    resetCamera: () => graphRef.current?.cameraPosition?.({ x: 0, y: 0, z: 820 }, { x: 0, y: 0, z: 0 }, reducedMotion ? 0 : 450),
    focusNode: (node) => graphRef.current?.cameraPosition?.({ x: node.x, y: node.y, z: node.z + 180 }, { x: node.x, y: node.y, z: node.z }, reducedMotion ? 0 : 500),
    freeze: () => graphRef.current?.pauseAnimation?.(),
    reheat: () => {
      graphRef.current?.resumeAnimation?.();
      graphRef.current?.d3ReheatSimulation?.();
    },
    resetLayout: () => {
      for (const node of graphData.nodes) {
        const position = deterministicCoordinates(node.id);
        Object.assign(node, { ...position, vx: 0, vy: 0, vz: 0 });
      }
      graphRef.current?.d3ReheatSimulation?.();
      graphRef.current?.zoomToFit?.(reducedMotion ? 0 : 500, 80);
    },
    exportPng: async () => {
      const canvas = containerRef.current?.querySelector("canvas");
      if (!canvas) throw new Error("Graph canvas is not available.");
      return canvas.toDataURL("image/png");
    }
  }), [graphData.nodes, reducedMotion]);

  try {
    return (
      <div ref={containerRef} className="h-full min-h-[560px]" aria-label="3D website topology graph canvas">
        <ForceGraph3D
          ref={graphRef as never}
          graphData={graphData}
          nodeId="id"
          nodeLabel={(node: RendererNode) => node.label}
          nodeVal={(node: RendererNode) => node.val}
          nodeColor={(node: RendererNode) => selectedNodeId === node.id ? "#111827" : node.color}
          linkWidth={(link: RendererEdge) => selectedEdgeId === link.id ? Math.max(3, link.width + 1) : link.width}
          linkColor={(link: RendererEdge) => selectedEdgeId === link.id ? "rgba(17,24,39,0.85)" : link.color}
          linkDirectionalArrowLength={showArrows ? 4 : 0}
          linkDirectionalArrowRelPos={1}
          linkOpacity={0.55}
          cooldownTicks={reducedMotion ? 20 : 120}
          backgroundColor={presentation ? "#fafaf9" : "#ffffff"}
          showNavInfo={false}
          onNodeClick={(node: RendererNode) => onNodeSelect(node)}
          onLinkClick={(link: RendererEdge) => onEdgeSelect(link)}
        />
        {!showLabels ? null : <div className="sr-only">Labels are available through node search and inspectors.</div>}
      </div>
    );
  } catch (error) {
    onError(error instanceof Error ? error : new Error("3D graph renderer failed."));
    return null;
  }
});
