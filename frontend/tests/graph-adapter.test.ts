import { describe, expect, it } from "vitest";

import { adaptGraphData, deterministicCoordinates, edgeWidth, nodeSize } from "../src/features/graph/graphDataAdapter";
import type { GraphDisplaySettings, GraphNode, GraphResponse } from "../src/types/graph";

const settings: GraphDisplaySettings = {
  mode: "3d",
  sizeBy: "uniform",
  colorBy: "status",
  labels: "selected",
  edgeWidthBy: "occurrences",
  showArrows: true,
  showIsolated: false,
  background: "light"
};

describe("graph data adapter", () => {
  it("converts API nodes and edges without mutating inputs", () => {
    const graph = graphFixture();
    const original = JSON.stringify(graph);

    const result = adaptGraphData(graph, settings);

    expect(result.nodes[0].id).toBe("snapshot:1");
    expect(result.nodes[0].x).toBe(deterministicCoordinates("snapshot:1").x);
    expect(result.nodes[0].z).not.toBe(0);
    expect(result.links[0].source).toBe("snapshot:1");
    expect(result.links[0].target).toBe("snapshot:2");
    expect(result.links[0].width).toBeGreaterThan(1);
    expect(result.legend.length).toBeGreaterThan(0);
    expect(JSON.stringify(graph)).toBe(original);
  });

  it("uses deterministic coordinates and bounded sizes", () => {
    const first = deterministicCoordinates("snapshot:stable");
    const second = deterministicCoordinates("snapshot:stable");

    expect(second).toEqual(first);
    expect(nodeSize(nodeFixture({ inbound_occurrence_count: 10_000 }), "inbound_occurrences")).toBeLessThanOrEqual(16);
    expect(nodeSize(nodeFixture({ inbound_occurrence_count: 0 }), "inbound_occurrences")).toBeGreaterThanOrEqual(3);
    expect(nodeSize(nodeFixture({}), "uniform")).toBe(5);
  });

  it("categorizes status, depth, host, and self-link edge widths", () => {
    const graph = graphFixture();

    expect(adaptGraphData(graph, { ...settings, colorBy: "depth" }).nodes[0].categoryLabel).toBe("Depth 0");
    expect(adaptGraphData(graph, { ...settings, colorBy: "host" }).nodes[0].categoryLabel).toBe("example.com");
    expect(edgeWidth(graph.edges[0], "uniform")).toBe(1.2);
    expect(edgeWidth(graph.edges[0], "occurrences")).toBeGreaterThan(1.2);
  });

  it("hides isolated nodes unless requested", () => {
    const graph = graphFixture();
    graph.nodes.push(nodeFixture({ id: "snapshot:3", snapshot_id: 3, path: "/isolated", is_starting_url: false }));

    expect(adaptGraphData(graph, settings).nodes.map((node) => node.id)).toEqual([
      "snapshot:1",
      "snapshot:2"
    ]);
    expect(adaptGraphData(graph, { ...settings, showIsolated: true }).nodes.map((node) => node.id)).toContain("snapshot:3");
  });
});

function graphFixture(): GraphResponse {
  return {
    scan: {
      id: 1,
      starting_url: "https://example.com/",
      status: "completed",
      website_property_id: null,
      website_property_name: null,
      created_at: "2026-01-01T00:00:00Z",
      finished_at: "2026-01-01T00:01:00Z"
    },
    summary: {
      total_available_nodes: 2,
      total_available_edges: 1,
      returned_nodes: 2,
      returned_edges: 1,
      fetched_nodes: 2,
      unfetched_nodes: 0,
      error_nodes: 0,
      self_link_edges: 0,
      total_occurrences: 4,
      truncated: false,
      truncation_reasons: [],
      focused: false,
      focus_snapshot_id: null,
      focus_hops: null
    },
    nodes: [nodeFixture({ id: "snapshot:1", snapshot_id: 1, crawl_depth: 0 }), nodeFixture({ id: "snapshot:2", snapshot_id: 2, path: "/pricing", inbound_occurrence_count: 4 })],
    edges: [{
      id: "1-2",
      source: "snapshot:1",
      target: "snapshot:2",
      source_snapshot_id: 1,
      target_snapshot_id: 2,
      target_resource_id: 2,
      occurrence_count: 4,
      unique_anchor_text_count: 2,
      nofollow_occurrence_count: 1,
      follow_occurrence_count: 3,
      empty_anchor_occurrence_count: 0,
      is_self_link: false,
      sample_anchor_texts: ["Pricing"],
      first_discovered_at: "2026-01-01T00:00:10Z",
      last_discovered_at: "2026-01-01T00:00:20Z",
      scope_decisions: { crawlable: 4 }
    }],
    effective_filters: {}
  };
}

function nodeFixture(overrides: Partial<GraphNode>): GraphNode {
  return {
    id: "snapshot:1",
    kind: "page",
    snapshot_id: 1,
    resource_id: 1,
    requested_url: "https://example.com/",
    final_url: "https://example.com/",
    page_title: "Home",
    host: "example.com",
    path: "/",
    http_status: 200,
    fetch_state: "fetched",
    error_type: null,
    crawl_depth: 0,
    content_type: "text/html",
    response_time_ms: 100,
    inbound_occurrence_count: 0,
    inbound_source_page_count: 0,
    outbound_occurrence_count: 4,
    outbound_target_page_count: 1,
    is_scan_seed: true,
    seed_origin_count: 1,
    is_starting_url: true,
    redirects: false,
    canonical_url: null,
    category: "2xx",
    ...overrides
  };
}
