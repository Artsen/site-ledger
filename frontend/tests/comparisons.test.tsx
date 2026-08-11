import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SiteComparisonsPanel } from "../src/components/SiteComparisonsPanel";
import type { Site } from "../src/types/scans";

const api = vi.hoisted(() => ({
  listComparisons: vi.fn(),
  listSiteScans: vi.fn(),
  createComparison: vi.fn(),
  getComparison: vi.fn(),
  getComparisonStatus: vi.fn(),
  rebuildComparison: vi.fn(),
  cancelComparison: vi.fn(),
  deleteComparison: vi.fn(),
  listComparisonPages: vi.fn(),
  listComparisonResources: vi.fn(),
  listComparisonLinks: vi.fn(),
}));

vi.mock("../src/api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../src/api/client")>()),
  ...api,
}));

const scans = [
  { id: 11, status: "completed", created_at: "2026-08-07T12:00:00Z" },
  { id: 10, status: "completed", created_at: "2026-08-06T12:00:00Z" },
];
const build = {
  id: 9,
  scan_comparison_id: 7,
  comparison_version: "scan-comparison-v2",
  algorithm_identity: "scan-comparison-v2|source-signals-v1|document-content-v2|incapsula-cb-v1|page-v2|resource-v1|link-v1|scan-projection-v1",
  status: "ready",
  baseline_projection_build_id: 4,
  target_projection_build_id: 5,
  baseline_projection_version: "scan-projection-v1",
  target_projection_version: "scan-projection-v1",
  baseline_projection_algorithm_identity: "projection",
  target_projection_algorithm_identity: "projection",
  baseline_projection_checksum: "a",
  target_projection_checksum: "b",
  baseline_scope_fingerprint: "scope",
  target_scope_fingerprint: "scope",
  baseline_seed_fingerprint: "seed",
  target_seed_fingerprint: "seed",
  coverage_state: "comparable",
  warnings_json: [],
  validation_json: {},
  comparison_checksum_sha256: "checksum",
  started_at: "2026-08-07T12:01:00Z",
  finished_at: "2026-08-07T12:01:01Z",
  failed_at: null,
  build_duration_ms: 1000,
  error_type: null,
  error_message: null,
  page_result_count: 1,
  resource_result_count: 0,
  link_result_count: 0,
  created_at: "2026-08-07T12:01:00Z",
};
const comparison = {
  id: 7,
  website_property_id: 1,
  baseline_scan_id: 10,
  target_scan_id: 11,
  current_build_id: 9,
  created_at: "2026-08-07T12:00:00Z",
  updated_at: "2026-08-07T12:01:00Z",
  baseline_scan: { ...scans[1], starting_url: "https://example.com/", started_at: null, finished_at: null, stop_reason: "queue_empty", failed_count: 0 },
  target_scan: { ...scans[0], starting_url: "https://example.com/", started_at: null, finished_at: null, stop_reason: "queue_empty", failed_count: 0 },
  current_build: build,
  active_build: null,
};

describe("Scan comparison workspace", () => {
  afterEach(cleanup);

  beforeEach(() => {
    vi.clearAllMocks();
    api.listSiteScans.mockResolvedValue({ items: scans, total: 2, limit: 250, offset: 0 });
    api.listComparisons.mockResolvedValue({ items: [], total: 0, limit: 100, offset: 0 });
    api.getComparisonStatus.mockResolvedValue({ comparison, summary: null });
    api.getComparison.mockResolvedValue({ comparison, summary: { pages: { newly_observed: 1, substantive_change: 1, technical_change: 2, normalization_only: 3 }, resources: { total: 0 }, links: { total: 0 }, scan: {} } });
    api.createComparison.mockResolvedValue({ comparison, summary: null });
    api.listComparisonPages.mockResolvedValue({ items: [{ id: 1, resource_id: 3, normalized_url: "https://example.com/old", host: "example.com", path: "/old", presence_state: "not_observed_in_target", change_state: "not_applicable", primary_change_class: "not_applicable", content_state: "not_applicable", document_content_state: "not_applicable", metadata_state: "not_applicable", technical_state: "not_applicable", exact_source_state: "not_applicable", head_state: "not_applicable", changed_field_count: 0, baseline_http_status: 200, target_http_status: null, response_time_ms_delta: null, network_bytes_delta: null }], total: 1, limit: 25, offset: 0, comparison_build_id: 9, comparison_version: "scan-comparison-v2" });
    api.listComparisonResources.mockResolvedValue({ items: [], total: 0, limit: 25, offset: 0, comparison_build_id: 9, comparison_version: "scan-comparison-v2" });
    api.listComparisonLinks.mockResolvedValue({ items: [], total: 0, limit: 25, offset: 0, comparison_build_id: 9, comparison_version: "scan-comparison-v2" });
  });

  it("defaults Baseline to the previous Scan and Target to the latest Scan", async () => {
    renderPanel("/sites/1?tab=comparisons");
    await waitFor(() => expect(screen.getByLabelText("Baseline Scan")).toHaveValue("10"));
    expect(screen.getByLabelText("Target Scan")).toHaveValue("11");
    fireEvent.click(screen.getByRole("button", { name: "Compare" }));
    await waitFor(() => expect(api.createComparison).toHaveBeenCalledWith("1", 10, 11));
  });

  it("shows preparation state without hiding an existing ready build", async () => {
    api.listComparisons.mockResolvedValue({ items: [{ ...comparison, active_build: { ...build, id: 10, status: "waiting_for_projections" } }], total: 1, limit: 100, offset: 0 });
    api.getComparisonStatus.mockResolvedValue({ comparison: { ...comparison, active_build: { ...build, id: 10, status: "waiting_for_projections" } }, summary: null });
    renderPanel("/sites/1?tab=comparisons&comparison_id=7");
    expect(await screen.findByText("Preparing Scan results")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /Pages/ })).toBeInTheDocument();
  });

  it("shows live comparison job progress", async () => {
    api.listComparisons.mockResolvedValue({ items: [{ ...comparison, active_build: { ...build, id: 10, status: "building" } }], total: 1, limit: 100, offset: 0 });
    api.getComparisonStatus.mockResolvedValue({
      comparison: { ...comparison, active_build: { ...build, id: 10, status: "building" } },
      summary: null,
      active_job: { id: 12, status: "running", current_operation: "comparing_pages", progress_current: 50, progress_total: 200, progress_unit: "pages", started_at: new Date().toISOString(), heartbeat_at: new Date().toISOString() },
    });
    renderPanel("/sites/1?tab=comparisons&comparison_id=7");
    expect(await screen.findByText(/50 of 200 pages \(25%\)/)).toBeInTheDocument();
    expect(screen.getByRole("progressbar", { name: "Comparison build progress" })).toHaveAttribute("aria-valuenow", "25");
  });

  it("reports substantive, technical, and normalization-only Pages separately", async () => {
    api.listComparisons.mockResolvedValue({ items: [comparison], total: 1, limit: 100, offset: 0 });
    renderPanel("/sites/1?tab=comparisons&comparison_id=7");
    expect(await screen.findByText("Substantive Change")).toBeInTheDocument();
    expect(screen.getByText("Technical Change")).toBeInTheDocument();
    expect(screen.getByText("Normalization Only")).toBeInTheDocument();
  });

  it("uses shared sortable headings and neutral absence wording", async () => {
    api.listComparisons.mockResolvedValue({ items: [comparison], total: 1, limit: 100, offset: 0 });
    renderPanel("/sites/1?tab=comparisons&comparison_id=7&comparison_tab=pages");
    expect(await screen.findByText("Not Observed In Target")).toBeInTheDocument();
    expect(screen.queryByText(/removed from website/i)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Sort URL ascending" }));
    await waitFor(() => expect(api.listComparisonPages).toHaveBeenLastCalledWith("1", "7", expect.stringContaining("sort=url")));
  });
});

function renderPanel(initialEntry: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<MemoryRouter initialEntries={[initialEntry]}><QueryClientProvider client={client}><SiteComparisonsPanel site={{ id: 1, name: "Example", base_url: "https://example.com/", display_timezone: "America/New_York" } as Site} /></QueryClientProvider></MemoryRouter>);
}
