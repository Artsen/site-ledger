import { forwardRef, useEffect, useImperativeHandle, useMemo, useRef } from "react";
import ForceGraph3D from "react-force-graph-3d";

import type { GraphRendererHandle, GraphRendererProps } from "./GraphRendererTypes";
import { deterministicCoordinates, type RendererEdge, type RendererNode } from "./graphDataAdapter";

type Point3D = { x: number; y: number; z: number };

type ForceGraph3DRef = {
  zoomToFit?: (duration?: number, padding?: number) => void;
  cameraPosition?: (position?: { x: number; y: number; z: number }, lookAt?: { x: number; y: number; z: number }, duration?: number) => void;
  controls?: () => { target: { set: (x: number, y: number, z: number) => void }; update: () => void };
  pauseAnimation?: () => void;
  resumeAnimation?: () => void;
  d3ReheatSimulation?: () => void;
};

export const ThreeDimensionalGraphRenderer = forwardRef<GraphRendererHandle, GraphRendererProps>(function ThreeDimensionalGraphRenderer(
  { data, selectedNodeId, selectedEdgeId, showArrows, presentation, reducedMotion, background, onNodeSelect, onEdgeSelect, onError },
  ref
) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const graphRef = useRef<ForceGraph3DRef | null>(null);
  const layout = useMemo(() => nestLayout(data.nodes), [data.nodes]);
  const graphData = useMemo(
    () => ({
      nodes: data.nodes.map((node) => {
        const position = layout.positions.get(node.id) ?? deterministicCoordinates(node.id);
        return { ...node, ...position, fx: position.x, fy: position.y, fz: position.z };
      }),
      links: data.links.map((link) => ({ ...link }))
    }),
    [data, layout.positions]
  );

  useEffect(() => {
    const fitTimer = window.setTimeout(() => {
      setOrbitTarget(graphRef.current, layout.center);
      graphRef.current?.zoomToFit?.(reducedMotion ? 0 : 250, 96);
    }, 80);
    return () => window.clearTimeout(fitTimer);
  }, [graphData, layout.center, reducedMotion]);

  useImperativeHandle(ref, () => ({
    fit: () => {
      setOrbitTarget(graphRef.current, layout.center);
      graphRef.current?.zoomToFit?.(reducedMotion ? 0 : 250, 96);
    },
    resetCamera: () => {
      setOrbitTarget(graphRef.current, layout.center);
      graphRef.current?.cameraPosition?.({ x: layout.center.x, y: layout.center.y, z: layout.center.z + 880 }, layout.center, reducedMotion ? 0 : 250);
    },
    focusNode: (node) => {
      const position = layout.positions.get(node.id) ?? node;
      graphRef.current?.cameraPosition?.({ x: position.x, y: position.y, z: position.z + 180 }, position, reducedMotion ? 0 : 250);
    },
    freeze: () => graphRef.current?.pauseAnimation?.(),
    reheat: () => {
      graphRef.current?.resumeAnimation?.();
      graphRef.current?.d3ReheatSimulation?.();
    },
    resetLayout: () => {
      for (const node of graphData.nodes) {
        const position = layout.positions.get(node.id) ?? deterministicCoordinates(node.id);
        Object.assign(node, { ...position, fx: position.x, fy: position.y, fz: position.z, vx: 0, vy: 0, vz: 0 });
      }
      setOrbitTarget(graphRef.current, layout.center);
      graphRef.current?.zoomToFit?.(reducedMotion ? 0 : 250, 96);
    },
    exportPng: async () => {
      const canvas = containerRef.current?.querySelector("canvas");
      if (!canvas) throw new Error("Graph canvas is not available.");
      return canvas.toDataURL("image/png");
    }
  }), [graphData.nodes, layout.center, layout.positions, reducedMotion]);

  try {
    const dark = background === "dark";
    return (
      <div ref={containerRef} className="relative h-full min-h-[560px]" aria-label="3D website topology graph canvas">
        <ForceGraph3D
          ref={graphRef as never}
          graphData={graphData}
          nodeId="id"
          nodeLabel={(node: RendererNode) => node.label}
          nodeVal={(node: RendererNode) => Math.max(2, Math.min(8, node.val))}
          nodeResolution={6}
          nodeColor={(node: RendererNode) => selectedNodeId === node.id ? dark ? "#f5f5f4" : "#111827" : node.color}
          linkWidth={(link: RendererEdge) => selectedEdgeId === link.id ? 2.5 : link.displayKind === "hierarchy" ? Math.min(1.2, link.width) : Math.min(0.7, link.width)}
          linkColor={(link: RendererEdge) => selectedEdgeId === link.id ? dark ? "rgba(245,245,244,0.9)" : "rgba(17,24,39,0.8)" : link.color}
          linkDirectionalArrowLength={(link: RendererEdge) => showArrows && link.displayKind === "page_link" ? 2.5 : 0}
          linkDirectionalArrowRelPos={1}
          linkOpacity={0.42}
          linkDirectionalParticles={(link: RendererEdge) => link.displayKind === "page_link" ? 1 : 0}
          linkDirectionalParticleWidth={(link: RendererEdge) => selectedEdgeId === link.id ? 1.8 : 0.8}
          linkDirectionalParticleSpeed={0.004}
          cooldownTicks={reducedMotion ? 1 : 8}
          warmupTicks={0}
          enableNodeDrag={false}
          backgroundColor={dark ? "#0c0a09" : presentation ? "#fafaf9" : "#ffffff"}
          showNavInfo={false}
          onNodeClick={(node: RendererNode) => onNodeSelect(node)}
          onLinkClick={(link: RendererEdge) => {
            if (link.selectable) onEdgeSelect(link);
          }}
        />
        <OrientationMap nodes={graphData.nodes} selectedNodeId={selectedNodeId} center={layout.center} dark={dark} />
      </div>
    );
  } catch (error) {
    onError(error instanceof Error ? error : new Error("3D graph renderer failed."));
    return null;
  }
});

function nestLayout(nodes: RendererNode[]) {
  const hostIndexes = new Map<string, number>();
  const hosts = Array.from(new Set(nodes.map((node) => node.host ?? "Unknown host"))).sort();
  hosts.forEach((host, index) => hostIndexes.set(host, index));
  const hostCount = Math.max(1, hosts.length);
  const positions = new Map<string, Point3D>();

  for (const node of nodes) {
    const base = deterministicCoordinates(node.id);
    const hostIndex = hostIndexes.get(node.host ?? "Unknown host") ?? 0;
    const hostAngle = (hostIndex / hostCount) * Math.PI * 2;
    const depth = Math.max(0, node.crawl_depth ?? 0);
    const shell = 120 + Math.min(8, depth) * 42;
    const hostRadius = hostCount === 1 ? 0 : Math.min(320, 110 + hostCount * 14);
    const localRadius = 80 + Math.sqrt(Math.abs(base.x) + Math.abs(base.y)) * 7;
    const localAngle = Math.atan2(base.y, base.x);
    positions.set(node.id, {
      x: Math.cos(hostAngle) * hostRadius + Math.cos(localAngle) * localRadius + Math.cos(base.z) * shell * 0.22,
      y: Math.sin(hostAngle) * hostRadius + Math.sin(localAngle) * localRadius + Math.sin(base.x) * shell * 0.22,
      z: (base.z * 0.72) + (depth - 2) * 36
    });
  }

  const center = centerOfMass(Array.from(positions.values()));
  for (const position of positions.values()) {
    position.x -= center.x;
    position.y -= center.y;
    position.z -= center.z;
  }
  return { positions, center: { x: 0, y: 0, z: 0 } };
}

function centerOfMass(points: Point3D[]) {
  if (!points.length) return { x: 0, y: 0, z: 0 };
  return {
    x: points.reduce((sum, point) => sum + point.x, 0) / points.length,
    y: points.reduce((sum, point) => sum + point.y, 0) / points.length,
    z: points.reduce((sum, point) => sum + point.z, 0) / points.length
  };
}

function setOrbitTarget(graph: ForceGraph3DRef | null, target: Point3D) {
  const controls = graph?.controls?.();
  controls?.target.set(target.x, target.y, target.z);
  controls?.update();
}

function OrientationMap({ nodes, selectedNodeId, center, dark }: { nodes: Array<RendererNode & Point3D>; selectedNodeId: string | null; center: Point3D; dark: boolean }) {
  const bounds = boundsFor(nodes);
  const points = nodes.slice(0, 600);
  return (
    <div className={`pointer-events-none absolute right-3 top-3 w-36 rounded-md border p-2 text-xs shadow-sm backdrop-blur ${dark ? "border-stone-700 bg-stone-950/85 text-stone-300" : "border-stone-200 bg-white/90 text-stone-600"}`}>
      <div className={`mb-1 font-medium ${dark ? "text-stone-100" : "text-stone-700"}`}>3D position</div>
      <svg viewBox="0 0 120 82" className={`h-20 w-full rounded border ${dark ? "border-stone-700 bg-stone-900" : "border-stone-200 bg-stone-50"}`} aria-hidden="true">
        <line x1="60" y1="8" x2="60" y2="74" stroke={dark ? "#44403c" : "#e7e5e4"} />
        <line x1="8" y1="41" x2="112" y2="41" stroke={dark ? "#44403c" : "#e7e5e4"} />
        {points.map((node) => {
          const point = projectPoint(node, bounds);
          return (
            <circle
              key={node.id}
              cx={point.x}
              cy={point.y}
              r={node.id === selectedNodeId ? 2.8 : 1.3}
              fill={node.id === selectedNodeId ? dark ? "#f5f5f4" : "#111827" : node.color}
              opacity={node.id === selectedNodeId ? 1 : 0.55}
            />
          );
        })}
        <circle cx={projectPoint(center, bounds).x} cy={projectPoint(center, bounds).y} r="3" fill="none" stroke={dark ? "#93c5fd" : "#2563eb"} strokeWidth="1.5" />
      </svg>
      <div className="mt-1">Center target</div>
    </div>
  );
}

function boundsFor(points: Point3D[]) {
  const xs = points.map((point) => point.x);
  const ys = points.map((point) => point.y);
  return {
    minX: Math.min(-1, ...xs),
    maxX: Math.max(1, ...xs),
    minY: Math.min(-1, ...ys),
    maxY: Math.max(1, ...ys)
  };
}

function projectPoint(point: Point3D, bounds: ReturnType<typeof boundsFor>) {
  const width = Math.max(1, bounds.maxX - bounds.minX);
  const height = Math.max(1, bounds.maxY - bounds.minY);
  return {
    x: 8 + ((point.x - bounds.minX) / width) * 104,
    y: 74 - ((point.y - bounds.minY) / height) * 66
  };
}
