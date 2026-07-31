import { forwardRef, useCallback, useImperativeHandle, useMemo, useRef, useState } from "react";

import type { GraphRendererHandle, GraphRendererProps } from "./GraphRendererTypes";
import { deterministicCoordinates, type RendererNode } from "./graphDataAdapter";

type ViewBox = { x: number; y: number; width: number; height: number };

const DEFAULT_VIEW_BOX: ViewBox = { x: -520, y: -400, width: 1040, height: 800 };

export const TwoDimensionalGraphRenderer = forwardRef<GraphRendererHandle, GraphRendererProps>(function TwoDimensionalGraphRenderer(
  { data, selectedNodeId, selectedEdgeId, showLabels, showArrows, presentation, onNodeSelect, onEdgeSelect, onError },
  ref
) {
  const svgRef = useRef<SVGSVGElement | null>(null);
  const [viewBox, setViewBox] = useState<ViewBox>(() => boundsFor(data.nodes));
  const nodeById = useMemo(() => new Map(data.nodes.map((node) => [node.id, node])), [data.nodes]);

  const fit = useCallback(() => {
    setViewBox(boundsFor(data.nodes));
  }, [data.nodes]);

  useImperativeHandle(ref, () => ({
    fit,
    resetCamera: () => setViewBox(DEFAULT_VIEW_BOX),
    focusNode: (node) => setViewBox({ x: node.x - 160, y: node.y - 120, width: 320, height: 240 }),
    freeze: () => undefined,
    reheat: () => undefined,
    resetLayout: () => {
      for (const node of data.nodes) {
        const position = deterministicCoordinates(node.id);
        node.x = position.x;
        node.y = position.y;
        node.z = 0;
      }
      fit();
    },
    exportPng: async () => {
      const svg = svgRef.current;
      if (!svg) throw new Error("Graph SVG is not available.");
      return svgToPng(svg);
    }
  }), [data.nodes, fit]);

  try {
    return (
      <div className="h-full min-h-[560px]" aria-label="2D website topology graph canvas">
        <svg
          ref={svgRef}
          role="img"
          aria-label="Static 2D website topology graph"
          className="h-full min-h-[560px] w-full"
          viewBox={`${viewBox.x} ${viewBox.y} ${viewBox.width} ${viewBox.height}`}
        >
          <defs>
            <marker id="graph-arrow" markerWidth="8" markerHeight="8" refX="7" refY="3" orient="auto" markerUnits="strokeWidth">
              <path d="M0,0 L0,6 L7,3 z" fill="#78716c" />
            </marker>
          </defs>
          <rect x={viewBox.x} y={viewBox.y} width={viewBox.width} height={viewBox.height} fill={presentation ? "#fafaf9" : "#ffffff"} />
          <g>
            {data.links.map((edge) => {
              const source = nodeById.get(String(edge.source));
              const target = nodeById.get(String(edge.target));
              if (!source || !target) return null;
              return (
                <line
                  key={edge.id}
                  x1={source.x}
                  y1={source.y}
                  x2={target.x}
                  y2={target.y}
                  stroke={selectedEdgeId === edge.id ? "rgba(17,24,39,0.9)" : edge.color}
                  strokeWidth={selectedEdgeId === edge.id ? Math.max(3, edge.width + 1) : edge.width}
                  markerEnd={showArrows ? "url(#graph-arrow)" : undefined}
                  className="cursor-pointer"
                  onClick={() => onEdgeSelect(edge)}
                />
              );
            })}
          </g>
          <g>
            {data.nodes.map((node) => (
              <g key={node.id} className="cursor-pointer" onClick={() => onNodeSelect(node)}>
                <circle
                  cx={node.x}
                  cy={node.y}
                  r={selectedNodeId === node.id ? node.val + 4 : node.val}
                  fill={selectedNodeId === node.id ? "#111827" : node.color}
                  stroke={node.is_starting_url ? "#111827" : "#ffffff"}
                  strokeWidth={node.is_starting_url ? 2.5 : 1.5}
                />
                <title>{node.label}</title>
                {showLabels && shouldRenderLabel(node, data.nodes.length, selectedNodeId) ? (
                  <text x={node.x + node.val + 5} y={node.y + 4} fontSize="11" fill="#44403c">
                    {node.label.slice(0, 72)}
                  </text>
                ) : null}
              </g>
            ))}
          </g>
        </svg>
      </div>
    );
  } catch (error) {
    onError(error instanceof Error ? error : new Error("2D graph renderer failed."));
    return null;
  }
});

function boundsFor(nodes: RendererNode[]): ViewBox {
  if (!nodes.length) return DEFAULT_VIEW_BOX;
  const padding = 96;
  const xs = nodes.map((node) => node.x);
  const ys = nodes.map((node) => node.y);
  const minX = Math.min(...xs) - padding;
  const maxX = Math.max(...xs) + padding;
  const minY = Math.min(...ys) - padding;
  const maxY = Math.max(...ys) + padding;
  return {
    x: minX,
    y: minY,
    width: Math.max(360, maxX - minX),
    height: Math.max(280, maxY - minY)
  };
}

function shouldRenderLabel(node: RendererNode, nodeCount: number, selectedNodeId: string | null) {
  return selectedNodeId === node.id || node.is_starting_url || node.is_scan_seed || nodeCount <= 80;
}

async function svgToPng(svg: SVGSVGElement) {
  const serialized = new XMLSerializer().serializeToString(svg);
  const blob = new Blob([serialized], { type: "image/svg+xml;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  try {
    const image = new Image();
    image.decoding = "async";
    const loaded = new Promise<void>((resolve, reject) => {
      image.onload = () => resolve();
      image.onerror = () => reject(new Error("Graph export failed."));
    });
    image.src = url;
    await loaded;
    const canvas = document.createElement("canvas");
    canvas.width = 1600;
    canvas.height = 1000;
    const context = canvas.getContext("2d");
    if (!context) throw new Error("Graph export canvas is unavailable.");
    context.fillStyle = "#ffffff";
    context.fillRect(0, 0, canvas.width, canvas.height);
    context.drawImage(image, 0, 0, canvas.width, canvas.height);
    return canvas.toDataURL("image/png");
  } finally {
    URL.revokeObjectURL(url);
  }
}
