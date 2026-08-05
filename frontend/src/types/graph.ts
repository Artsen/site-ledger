import type { LinkOccurrence, Scan } from "./scans";

export type GraphNodeKind = "page" | "discovered";

export type GraphNode = {
  id: string;
  kind: GraphNodeKind;
  snapshot_id: number | null;
  resource_id: number | null;
  requested_url: string | null;
  final_url: string | null;
  page_title: string | null;
  host: string | null;
  path: string | null;
  http_status: number | null;
  fetch_state: string | null;
  error_type: string | null;
  crawl_depth: number | null;
  content_type: string | null;
  response_time_ms: number | null;
  inbound_occurrence_count: number;
  inbound_source_page_count: number;
  outbound_occurrence_count: number;
  outbound_target_page_count: number;
  is_scan_seed: boolean;
  seed_origin_count: number;
  is_starting_url: boolean;
  redirects: boolean;
  canonical_url: string | null;
  category: string | null;
};

export type GraphEdge = {
  id: string;
  source: string;
  target: string;
  source_snapshot_id: number;
  target_snapshot_id: number | null;
  target_resource_id: number | null;
  occurrence_count: number;
  unique_anchor_text_count: number;
  nofollow_occurrence_count: number;
  follow_occurrence_count: number;
  empty_anchor_occurrence_count: number;
  is_self_link: boolean;
  sample_anchor_texts: string[];
  first_discovered_at: string | null;
  last_discovered_at: string | null;
  scope_decisions: Record<string, number>;
  role_counts?: Record<string, number>;
  dom_regions: Record<string, number>;
};

export type GraphResponse = {
  scan: Pick<Scan, "id" | "starting_url" | "status" | "website_property_id" | "website_property_name" | "created_at" | "finished_at">;
  summary: {
    total_available_nodes: number;
    total_available_edges: number;
    returned_nodes: number;
    returned_edges: number;
    fetched_nodes: number;
    unfetched_nodes: number;
    error_nodes: number;
    self_link_edges: number;
    total_occurrences: number;
    truncated: boolean;
    truncation_reasons: string[];
    focused: boolean;
    focus_snapshot_id: number | null;
    focus_hops: number | null;
  };
  nodes: GraphNode[];
  edges: GraphEdge[];
  effective_filters: Record<string, string | number | boolean | null>;
};

export type GraphCapabilities = {
  default_node_limit: number;
  maximum_node_limit: number;
  default_edge_limit: number;
  maximum_edge_limit: number;
  default_focus_hops: number;
  maximum_focus_hops: number;
  sample_anchor_limit: number;
  occurrence_page_default: number;
  occurrence_page_maximum: number;
  supported_status_filters: string[];
  supported_error_filters: string[];
  supported_node_size_modes: string[];
  supported_node_category_modes: string[];
};

export type GraphEdgeOccurrence = LinkOccurrence & {
  source_snapshot_id: number;
  target_snapshot_id: number | null;
  is_self_link: boolean;
};

export type GraphEdgeOccurrenceList = {
  items: GraphEdgeOccurrence[];
  total: number;
  limit: number;
  offset: number;
  edge: GraphEdge | null;
};

export type GraphMode = "2d" | "3d";
export type GraphSizeBy = "uniform" | "inbound_sources" | "inbound_occurrences" | "outbound_targets" | "outbound_occurrences" | "response_time" | "depth_inverse";
export type GraphColorBy = "status" | "fetch_state" | "depth" | "host" | "path" | "error" | "seed";
export type GraphLabels = "hide" | "selected" | "important" | "all";
export type GraphEdgeWidthBy = "uniform" | "occurrences";
export type GraphBackground = "light" | "dark";
export type GraphLinkVisibility = "selected" | "all" | "hidden";
export type GraphLinkCategoryFilter = "all" | "content" | "navigation" | "template";

export type GraphDisplaySettings = {
  mode: GraphMode;
  sizeBy: GraphSizeBy;
  colorBy: GraphColorBy;
  labels: GraphLabels;
  edgeWidthBy: GraphEdgeWidthBy;
  showArrows: boolean;
  showIsolated: boolean;
  background: GraphBackground;
  linkVisibility: GraphLinkVisibility;
  linkCategoryFilter: GraphLinkCategoryFilter;
};
