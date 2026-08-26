import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { forwardRef, useImperativeHandle } from "react";

import { AppShell } from "../src/components/AppShell";
import { CopyButton } from "../src/components/ui/CopyButton";
import { StatusBadge } from "../src/components/ui/StatusBadge";
import { displayError } from "../src/utils/errors";
import { useDocumentTitle } from "../src/utils/useDocumentTitle";
import { NewScanPage } from "../src/pages/NewScanPage";
import { PageDetailPage } from "../src/pages/PageDetailPage";
import { PersistentPageDetailPage } from "../src/pages/PersistentPageDetailPage";
import { ScanDetailPage } from "../src/pages/ScanDetailPage";
import { ScansPage } from "../src/pages/ScansPage";
import { SiteDetailPage } from "../src/pages/SiteDetailPage";
import { SiteFormPage } from "../src/pages/SiteFormPage";
import { SitesPage } from "../src/pages/SitesPage";
import type { PageList, ResourceInventoryItem, Scan, Snapshot } from "../src/types/scans";

const api = vi.hoisted(() => ({
  createScan: vi.fn(),
  getScan: vi.fn(),
  getScanProjectionStatus: vi.fn(),
  buildScanProjection: vi.fn(),
  rebuildScanProjection: vi.fn(),
  listPages: vi.fn(),
  listErrors: vi.fn(),
  getSnapshot: vi.fn(),
  getSnapshotStructuredContent: vi.fn(),
  prepareSnapshotStructuredContent: vi.fn(),
  getStaticFetchAttempts: vi.fn(),
  getLinks: vi.fn(),
  getInboundLinks: vi.fn(),
  getHtml: vi.fn(),
  cancelScan: vi.fn(),
  getScanDeletePreview: vi.fn(),
  deleteScan: vi.fn(),
  listScanHistory: vi.fn(),
  listScans: vi.fn(),
  listSites: vi.fn(),
  getSite: vi.fn(),
  createSite: vi.fn(),
  updateSite: vi.fn(),
  deleteSite: vi.fn(),
  createSiteScan: vi.fn(),
  listSiteScans: vi.fn(),
  listSources: vi.fn(),
  createSource: vi.fn(),
  deleteSource: vi.fn(),
  refreshSource: vi.fn(),
  bulkRefreshSources: vi.fn(),
  cancelSourceRefresh: vi.fn(),
  discoverRobots: vi.fn(),
  discoverAiDocumentSources: vi.fn(),
  createAiDocumentSource: vi.fn(),
  listSourceEntries: vi.fn(),
  addManualUrls: vi.fn(),
  removeManualSourceEntry: vi.fn(),
  listInventory: vi.fn(),
  bulkDeleteInventoryEntries: vi.fn(),
  createInventorySuppression: vi.fn(),
  deleteInventorySuppression: vi.fn(),
  bulkCreateInventorySuppressions: vi.fn(),
  bulkRestoreInventorySuppressions: vi.fn(),
  listSitePages: vi.fn(),
  getSitePage: vi.fn(),
  getPageStructuredContent: vi.fn(),
  preparePageStructuredContent: vi.fn(),
  listPageObservations: vi.fn(),
  updatePageMetadata: vi.fn(),
  updatePageWorkspaceState: vi.fn(),
  bulkDeletePages: vi.fn(),
  listPageCategories: vi.fn(),
  createPageCategory: vi.fn(),
  updatePageCategory: vi.fn(),
  deletePageCategory: vi.fn(),
  bulkPageCategories: vi.fn(),
  bulkPageMetadata: vi.fn(),
  bulkPageWorkspaceState: vi.fn(),
  listSiteNotes: vi.fn(),
  createSiteNote: vi.fn(),
  listScanNotes: vi.fn(),
  createScanNote: vi.fn(),
  listPageNotes: vi.fn(),
  createPageNote: vi.fn(),
  updateNote: vi.fn(),
  deleteNote: vi.fn(),
  listScanSeeds: vi.fn(),
  listJobs: vi.fn(),
  getJob: vi.fn(),
  getWorkerHealth: vi.fn(),
  getGraphCapabilities: vi.fn(),
  getScanGraph: vi.fn(),
  getGraphEdgeOccurrences: vi.fn(),
  getRenderCapabilities: vi.fn(),
  getRenderedObservation: vi.fn(),
  getRenderedNetwork: vi.fn(),
  getRenderedConsole: vi.fn(),
  getRenderedErrors: vi.fn(),
  listScanResources: vi.fn(),
  getScanResourceSummary: vi.fn(),
  listSiteResources: vi.fn(),
  getSiteResourceSummary: vi.fn(),
  listScanRenderedObservations: vi.fn(),
  renderedArtifactUrl: vi.fn((id: number) => `/api/rendered-artifacts/${id}/content`)
}));

vi.mock("../src/api/client", () => ({
  ...api,
  defaultScope: () => ({
    allowed_host_patterns: [],
    excluded_host_patterns: [],
    included_path_prefixes: ["/"],
    excluded_path_prefixes: ["/wp-admin/", "/wp-login.php"],
    follow_subdomains: false,
    max_pages: 100,
    max_depth: 3,
    respect_robots_txt: false,
  request_timeout_seconds: 10,
  static_max_attempts: 2,
  static_retry_initial_delay_ms: 500,
  static_retry_max_delay_ms: 5000,
    max_html_response_bytes: 2000000,
    concurrent_requests_per_host: 2,
    delay_between_requests_ms: 0,
    user_agent: "WebsiteScanner/0.1",
    drop_query_parameters: ["utm_*", "gclid", "fbclid", "msclkid"],
    allow_private_networks: false,
    max_redirects: 10,
    enable_http_revalidation: true,
    enable_parse_reuse: true,
    render_mode: "none", render_max_pages: 10, render_viewport_width: 1440, render_viewport_height: 900,
    render_device_scale_factor: 1, render_locale: "en-US", render_timezone: "UTC", render_color_scheme: "light",
    render_reduced_motion: "reduce", render_navigation_timeout_seconds: 30, render_load_timeout_seconds: 10,
    render_capture_full_page: true, render_max_full_page_height: 20000, render_max_dom_bytes: 5000000,
    render_max_screenshot_bytes: 15000000, render_max_network_entries: 1000, render_max_console_entries: 200,
    render_max_page_errors: 50, render_max_page_duration_seconds: 60, render_max_total_network_bytes: 50000000,
    render_max_resource_bytes: 10000000
  })
}));

vi.mock("../src/features/graph/TwoDimensionalGraphRenderer", () => ({
  TwoDimensionalGraphRenderer: forwardRef(function MockTwoDimensionalGraphRenderer(props: {
    data: { nodes: Array<{ id: string; label: string }>; links: Array<{ id: string; label: string }> };
    onNodeSelect: (node: { id: string; label: string }) => void;
    onEdgeSelect: (edge: { id: string; label: string }) => void;
  }, ref) {
    useImperativeHandle(ref, () => ({ fit: vi.fn(), resetCamera: vi.fn(), focusNode: vi.fn(), freeze: vi.fn(), reheat: vi.fn(), resetLayout: vi.fn(), exportPng: vi.fn().mockResolvedValue("data:image/png;base64,abc") }));
    return <div aria-label="mock 2D graph">{props.data.nodes.map((node) => <button key={node.id} onClick={() => props.onNodeSelect(node)}>{node.label}</button>)}{props.data.links.map((edge) => <button key={edge.id} onClick={() => props.onEdgeSelect(edge)}>{edge.label}</button>)}</div>;
  })
}));

vi.mock("../src/features/graph/ThreeDimensionalGraphRenderer", () => ({
  ThreeDimensionalGraphRenderer: forwardRef(function MockThreeDimensionalGraphRenderer(props: {
    data: { nodes: Array<{ id: string; label: string }>; links: Array<{ id: string; label: string }> };
    onNodeSelect: (node: { id: string; label: string }) => void;
    onEdgeSelect: (edge: { id: string; label: string }) => void;
  }, ref) {
    useImperativeHandle(ref, () => ({ fit: vi.fn(), resetCamera: vi.fn(), focusNode: vi.fn(), freeze: vi.fn(), reheat: vi.fn(), resetLayout: vi.fn(), exportPng: vi.fn().mockResolvedValue("data:image/png;base64,abc") }));
    return <div aria-label="mock 3D graph">{props.data.nodes.map((node) => <button key={node.id} onClick={() => props.onNodeSelect(node)}>{node.label}</button>)}{props.data.links.map((edge) => <button key={edge.id} onClick={() => props.onEdgeSelect(edge)}>{edge.label}</button>)}</div>;
  })
}));

beforeEach(() => {
  window.localStorage.clear();
  vi.useRealTimers();
  Object.values(api).forEach((mock) => mock.mockReset());
  api.createScan.mockResolvedValue({ id: 44 });
  api.getScan.mockResolvedValue(scanFixture);
  api.getScanProjectionStatus.mockResolvedValue({
    scan_id: scanFixture.id,
    scan_status: scanFixture.status,
    expected_version: "scan-projection-v1",
    projection_source: "materialized",
    projection_status: "ready",
    current_build: { id: 9 },
    active_build: null,
    latest_build: null,
    can_build: false,
    can_rebuild: true
  });
  api.buildScanProjection.mockResolvedValue({ id: 1 });
  api.rebuildScanProjection.mockResolvedValue({ id: 2 });
  api.listPages.mockResolvedValue(emptyPageList);
  api.listErrors.mockResolvedValue([]);
  api.getSnapshot.mockResolvedValue(snapshotFixture);
  api.getStaticFetchAttempts.mockResolvedValue([
    {
      id: 1,
      snapshot_id: 9,
      attempt_number: 1,
      started_at: "2026-07-30T01:00:01Z",
      finished_at: "2026-07-30T01:00:11Z",
      requested_url: "https://example.com/page",
      final_url: null,
      retrieval_http_status: null,
      response_time_ms: 10000,
      outcome: "failed",
      error_type: "connection_timeout",
      error_message: "Connection timed out",
      redirect_chain: [],
      network_bytes_transferred: 0,
      retryable: true,
      retry_reason: "connection_timeout",
      created_at: "2026-07-30T01:00:11Z"
    },
    {
      id: 2,
      snapshot_id: 9,
      attempt_number: 2,
      started_at: "2026-07-30T01:00:12Z",
      finished_at: "2026-07-30T01:00:12Z",
      requested_url: "https://example.com/page",
      final_url: "https://example.com/page",
      retrieval_http_status: 200,
      response_time_ms: 50,
      outcome: "succeeded",
      error_type: null,
      error_message: null,
      redirect_chain: [],
      network_bytes_transferred: 1200,
      retryable: false,
      retry_reason: null,
      created_at: "2026-07-30T01:00:12Z"
    }
  ]);
  api.getLinks.mockResolvedValue(linkFixtures);
  api.getInboundLinks.mockResolvedValue(inboundFixture);
  api.getHtml.mockResolvedValue("<html><body><script>window.executed = true</script><h1>Source</h1></body></html>");
  api.getRenderCapabilities.mockResolvedValue({
    defaults: {},
    limits: { render_max_pages: { minimum: 1, maximum: 1000 } },
    supported_modes: ["none", "starting_page", "all_eligible"],
    browser_engine: "chromium",
    artifact_types: ["rendered_dom", "viewport_screenshot", "full_page_screenshot"],
    allowed_request_methods: ["GET", "HEAD", "OPTIONS"],
    service_workers: "blocked"
  });
  api.getRenderedObservation.mockRejectedValue(new Error("Snapshot has no rendered observation"));
  api.listScanResources.mockResolvedValue({ items: [], total: 0, limit: 50, offset: 0 });
  api.listSiteResources.mockResolvedValue({ items: [], total: 0, limit: 50, offset: 0 });
  api.getScanResourceSummary.mockResolvedValue({ unique_resources: 0, observed_resources: 0, discovered_only_resources: 0, total_occurrences: 0, kind_counts: {} });
  api.getSiteResourceSummary.mockResolvedValue({ unique_resources: 0, observed_resources: 0, discovered_only_resources: 0, total_occurrences: 0, kind_counts: {} });
  api.listScanRenderedObservations.mockResolvedValue({ items: [], total: 0, limit: 50, offset: 0 });
  api.cancelScan.mockResolvedValue({ ...scanFixture, status: "cancelled" });
  api.getScanDeletePreview.mockResolvedValue({
    scan_id: 1,
    starting_url: "https://example.com/",
    can_delete: true,
    status: "completed",
    snapshots: 2,
    link_occurrences: 3,
    unique_resources: 2,
    html_blobs_referenced: 2,
    exclusive_html_blobs: 1,
    shared_html_blobs: 1,
    html_blobs_deleted: 1,
    raw_html_bytes_reclaimable: 1200,
    stored_html_bytes_reclaimable: 500,
    reason: null,
    warnings: []
  });
  api.deleteScan.mockResolvedValue({
    deleted_scan_id: 1,
    snapshots_deleted: 2,
    link_occurrences_deleted: 3,
    resources_deleted: 1,
    html_blob_records_deleted: 1,
    html_blob_files_deleted: 1,
    html_blobs_deleted: 1,
    raw_html_bytes_reclaimed: 1200,
    stored_html_bytes_reclaimed: 500,
    warnings: []
  });
  api.listScanHistory.mockResolvedValue({ items: [scanFixture], total: 1, limit: 25, offset: 0 });
  api.listScans.mockResolvedValue([]);
  api.listSites.mockResolvedValue({ items: [siteFixture], total: 1, limit: 25, offset: 0 });
  api.getSite.mockResolvedValue(siteDetailFixture);
  api.createSite.mockResolvedValue(siteDetailFixture);
  api.updateSite.mockResolvedValue(siteDetailFixture);
  api.deleteSite.mockResolvedValue({ deleted_site_id: 3 });
  api.createSiteScan.mockResolvedValue({ ...scanFixture, id: 45, website_property_id: 3, website_property_name: "Example Site", website_property_base_url: "https://example.com/" });
  api.listSiteScans.mockResolvedValue({ items: [{ ...scanFixture, website_property_id: 3, website_property_name: "Example Site", website_property_base_url: "https://example.com/" }], total: 1, limit: 25, offset: 0 });
  api.listSources.mockResolvedValue({ items: [sourceFixture], total: 1, limit: 25, offset: 0 });
  api.createSource.mockResolvedValue(sourceFixture);
  api.deleteSource.mockResolvedValue({ deleted_source_id: 4 });
  api.refreshSource.mockResolvedValue(refreshFixture);
  api.bulkRefreshSources.mockResolvedValue([refreshFixture]);
  api.cancelSourceRefresh.mockResolvedValue({ ...refreshFixture, status: "cancelled" });
  api.discoverRobots.mockResolvedValue(refreshFixture);
  api.listSourceEntries.mockResolvedValue({ items: [], total: 0, limit: 50, offset: 0 });
  api.addManualUrls.mockResolvedValue({ source: sourceFixture, items: [], accepted_count: 1, rejected_count: 1, duplicate_count: 0 });
  api.removeManualSourceEntry.mockResolvedValue({});
  api.bulkDeleteInventoryEntries.mockResolvedValue({ selected: 2, changed: 2, unchanged: 0, rejected: 0 });
  api.createInventorySuppression.mockResolvedValue({ id: 15 });
  api.deleteInventorySuppression.mockResolvedValue({ deleted_suppression_id: 15 });
  api.bulkCreateInventorySuppressions.mockResolvedValue({ selected: 1, changed: 1, unchanged: 0, rejected: 0 });
  api.bulkRestoreInventorySuppressions.mockResolvedValue({ selected: 1, changed: 1, unchanged: 0, rejected: 0 });
  api.listInventory.mockResolvedValue({ items: [inventoryFixture], total: 1, limit: 50, offset: 0 });
  api.listSitePages.mockResolvedValue({ items: [persistentPageFixture], total: 1, limit: 50, offset: 0 });
  api.getSitePage.mockResolvedValue({ page: persistentPageFixture, site_id: 3, site_name: "Example Site" });
  api.updatePageWorkspaceState.mockResolvedValue({ page: persistentPageFixture, site_id: 3, site_name: "Example Site" });
  api.bulkDeletePages.mockResolvedValue({ selected: 1, changed: 1, unchanged: 0, rejected: 0 });
  api.bulkPageWorkspaceState.mockResolvedValue({ selected: 1, changed: 1, unchanged: 0, rejected: 0 });
  api.listPageObservations.mockResolvedValue({ items: [pageObservationFixture], total: 1, limit: 50, offset: 0 });
  api.listPageCategories.mockResolvedValue({ items: [], total: 0, limit: 200, offset: 0 });
  api.listSiteNotes.mockResolvedValue({ items: [], total: 0, limit: 25, offset: 0 });
  api.listScanNotes.mockResolvedValue({ items: [], total: 0, limit: 25, offset: 0 });
  api.listPageNotes.mockResolvedValue({ items: [], total: 0, limit: 25, offset: 0 });
  api.listScanSeeds.mockResolvedValue({ items: [seedFixture], total: 1, limit: 50, offset: 0 });
  api.listJobs.mockResolvedValue({ items: [], total: 0, limit: 50, offset: 0 });
  api.getJob.mockResolvedValue(jobFixture);
  api.getWorkerHealth.mockResolvedValue(workerHealthFixture);
  api.getGraphCapabilities.mockResolvedValue(graphCapabilitiesFixture);
  api.getScanGraph.mockResolvedValue(graphFixture);
  api.getGraphEdgeOccurrences.mockResolvedValue(edgeOccurrenceFixture);
});

afterEach(() => cleanup());

describe("Site Ledger product identity", () => {
  it("renders the accessible shell brand, mark, and desktop tagline", async () => {
    renderShell("/scans/new");

    const brandLink = screen.getByRole("link", { name: "Site Ledger Sites" });
    expect(brandLink).toHaveAttribute("href", "/sites");
    expect(brandLink.querySelector("svg")).toBeInTheDocument();
    expect(screen.getAllByText("Site Ledger").length).toBeGreaterThan(0);
    expect(screen.getByText("A historical record of your website.")).toBeInTheDocument();
    expect(screen.queryByText("Website Scanner")).not.toBeInTheDocument();
    await waitFor(() => expect(document.title).toBe("New Scan | Site Ledger"));
  });

  it("updates titles for entity routes after data loads", async () => {
    const view = renderRoute(<SiteDetailPage />, "/sites/:siteId", "/sites/3");
    await screen.findByRole("heading", { name: "Example Site" });
    await waitFor(() => expect(document.title).toBe("Example Site | Site Ledger"));

    view.unmount();
    renderRoute(<PageDetailPage />, "/scans/:scanId/pages/:snapshotId", "/scans/1/pages/9");
    await screen.findByRole("heading", { name: "Example page" });
    await waitFor(() => expect(document.title).toBe("Example page | Site Ledger"));
  });

  it("uses the product name when a page title is unavailable", async () => {
    function UntitledRoute() {
      useDocumentTitle();
      return <div>Untitled route</div>;
    }

    render(<UntitledRoute />);
    await waitFor(() => expect(document.title).toBe("Site Ledger"));
  });
});

describe("new scan workflow", () => {
  it("validates and normalizes a bare hostname while showing exact-host scope", async () => {
    renderRoute(<NewScanPage />, "/scans/new");

    fireEvent.change(screen.getByLabelText("Starting URL"), { target: { value: "example.com" } });
    fireEvent.blur(screen.getByLabelText("Starting URL"));

    expect(screen.getByLabelText("Starting URL")).toHaveValue("https://example.com/");
    expect(screen.getByText(/Exact hostname: example.com/i)).toBeInTheDocument();
    expect(screen.getByText(/Subdomains excluded/i)).toBeInTheDocument();
  });

  it("rejects unsupported schemes and invalid numeric values", () => {
    renderRoute(<NewScanPage />, "/scans/new");

    fireEvent.change(screen.getByLabelText("Starting URL"), { target: { value: "ftp://example.com" } });
    fireEvent.change(screen.getByLabelText("Maximum pages"), { target: { value: "0" } });

    expect(screen.getByText(/Only HTTP and HTTPS URLs can be scanned/i)).toBeInTheDocument();
    expect(screen.getByText(/Maximum pages must be between/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Start scan" })).toBeDisabled();
  });

  it("preserves list newlines while editing and parses one item per line on submission", async () => {
    renderRoute(<NewScanPage />, "/scans/new");

    fireEvent.change(screen.getByLabelText("Starting URL"), { target: { value: "https://example.com/" } });
    fireEvent.click(screen.getByText("Advanced scope settings"));
    fireEvent.change(screen.getByLabelText("Allowed hosts"), { target: { value: "example.com\nblog.example.com\n" } });

    expect(screen.getByLabelText("Allowed hosts")).toHaveValue("example.com\nblog.example.com\n");
    fireEvent.click(screen.getByRole("button", { name: "Start scan" }));

    await waitFor(() => expect(api.createScan).toHaveBeenCalledTimes(1));
    expect(api.createScan.mock.calls[0][1].allowed_host_patterns).toEqual(["example.com", "blog.example.com"]);
  });

  it("prevents duplicate submission while a scan is being created", async () => {
    let resolveScan: (value: unknown) => void = () => undefined;
    api.createScan.mockReturnValue(new Promise((resolve) => { resolveScan = resolve; }));
    renderRoute(<NewScanPage />, "/scans/new");

    fireEvent.change(screen.getByLabelText("Starting URL"), { target: { value: "https://example.com/" } });
    const button = screen.getByRole("button", { name: "Start scan" });
    fireEvent.click(button);
    fireEvent.click(button);

    await waitFor(() => expect(api.createScan).toHaveBeenCalledTimes(1));
    resolveScan({ id: 44 });
  });

  it("submits ad-hoc Scan browser rendering settings without requiring a saved Site", async () => {
    renderRoute(<NewScanPage />, "/scans/new");
    fireEvent.change(screen.getByLabelText("Starting URL"), { target: { value: "https://example.com/" } });
    fireEvent.change(screen.getByLabelText("Render mode"), { target: { value: "all_eligible" } });
    fireEvent.change(screen.getByLabelText("Maximum rendered pages"), { target: { value: "2" } });
    fireEvent.click(screen.getByRole("button", { name: "Start scan" }));
    await waitFor(() => expect(api.createScan).toHaveBeenCalled());
    expect(api.createScan.mock.calls[0][1]).toMatchObject({ render_mode: "all_eligible", render_max_pages: 2 });
    expect(api.createSiteScan).not.toHaveBeenCalled();
  });
});

describe("scan results workflow", () => {
  it("shows an ad-hoc Scan Render Run in Scan context", async () => {
    api.getScan.mockResolvedValue({
      ...scanFixture,
      website_property_id: null,
      website_property_name: null,
      render_run_id: 77,
      render_run_status: "running",
      scope_config: { ...scanFixture.scope_config, render_mode: "all_eligible" }
    });
    api.listScanRenderedObservations.mockResolvedValue({
      items: [],
      total: 0,
      limit: 50,
      offset: 0,
      summary: { successful_renders: 0, no_content_responses: 0, redirect_responses: 0, http_error_responses: 0, rate_limited: 0, skipped_after_throttling: 0, technical_failures: 0, artifacts_retained: 0 }
    });

    renderRoute(<ScanDetailPage />, "/scans/:scanId", "/scans/1?tab=rendered");

    expect(await screen.findByText("Browser Render Run #77")).toBeInTheDocument();
    expect(screen.getByText("Running")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "View rendered observations" })).toHaveAttribute("href", "/scans/1?tab=rendered");
    await waitFor(() => expect(api.listScanRenderedObservations).toHaveBeenCalledWith("1", expect.any(String)));
  });

  it("keeps Resource search stable and resets filters when changing Scan tabs", async () => {
    renderRoute(<ScanDetailPage />, "/scans/:scanId", "/scans/1?tab=resources");

    fireEvent.change(await screen.findByLabelText("Search Resources"), { target: { value: "guide" } });
    await waitFor(() => expect(api.listScanResources).toHaveBeenLastCalledWith("1", expect.stringContaining("search=guide")));
    await new Promise((resolve) => window.setTimeout(resolve, 450));
    expect(screen.getByLabelText("Search Resources")).toHaveValue("guide");

    fireEvent.click(screen.getByRole("tab", { name: /Pages/i }));
    expect(await screen.findByLabelText("Search pages")).toHaveValue("");
    fireEvent.change(screen.getByLabelText("Search pages"), { target: { value: "pricing" } });
    await waitFor(() => expect(api.listPages).toHaveBeenLastCalledWith("1", expect.stringContaining("search=pricing")));

    fireEvent.click(screen.getByRole("tab", { name: /Resources/i }));
    expect(await screen.findByLabelText("Search Resources")).toHaveValue("");
  });

  it("keeps terminal evidence usable while optimized results are building", async () => {
    api.getScanProjectionStatus.mockResolvedValue({
      scan_id: 1,
      scan_status: "completed",
      expected_version: "scan-projection-v1",
      projection_source: "dynamic",
      projection_status: "building",
      current_build: null,
      active_build: null,
      latest_build: null,
      can_build: false,
      can_rebuild: false
    });
    renderRoute(<ScanDetailPage />, "/scans/:scanId", "/scans/1?tab=resources");

    expect(await screen.findByText("Building optimized results")).toBeInTheDocument();
    expect(screen.getByText("Preparing optimized results. Current evidence remains available.")).toBeInTheDocument();
    expect(api.listScanResources).toHaveBeenCalled();
  });

  it("offers an accessible rebuild action for prepared terminal results", async () => {
    renderRoute(<ScanDetailPage />, "/scans/:scanId", "/scans/1");

    fireEvent.click(await screen.findByRole("button", { name: "Rebuild results" }));

    await waitFor(() => expect(api.rebuildScanProjection).toHaveBeenCalledWith("1"));
  });

  it("lists and filters observed and discovered Resources", async () => {
    api.getScan.mockResolvedValue({ ...scanFixture, resource_discovered_count: 2 });
    api.getScanResourceSummary.mockResolvedValue({ unique_resources: 2, observed_resources: 1, discovered_only_resources: 1, total_occurrences: 4, kind_counts: { document: 1, image: 1, script: 0, stylesheet: 0, font: 0 } });
    api.listScanResources.mockResolvedValue({
      total: 2, limit: 50, offset: 0, items: [
        resourceFixture({ resource_id: 21, normalized_url: "https://example.com/guide.pdf", effective_kind: "document", effective_kind_label: "Document", observed: true, discovered_only: false, normalized_mime_type: "application/pdf", http_status: 200 }),
        resourceFixture({ resource_id: 22, normalized_url: "https://example.com/hero.webp", effective_kind: "image", effective_kind_label: "Image", observed: false, discovered_only: true, normalized_mime_type: null, http_status: null })
      ]
    });
    renderRoute(<ScanDetailPage />, "/scans/:scanId", "/scans/1?tab=resources");

    expect(await screen.findByText("https://example.com/guide.pdf")).toBeInTheDocument();
    expect(screen.getByText("https://example.com/hero.webp")).toBeInTheDocument();
    expect(screen.getAllByText("Observed").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Discovered only").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Document").length).toBeGreaterThan(0);
    expect(screen.getAllByRole("navigation", { name: "Resources pagination" })).toHaveLength(2);
    fireEvent.change(screen.getAllByLabelText("Resource rows per page")[0], { target: { value: "100" } });
    await waitFor(() => expect(screen.getAllByLabelText("Resource rows per page").every((control) => (control as HTMLSelectElement).value === "100")).toBe(true));
    await waitFor(() => expect(api.listScanResources).toHaveBeenLastCalledWith("1", expect.stringContaining("limit=100")));
    fireEvent.change(screen.getByLabelText("Resource kind"), { target: { value: "document" } });
    await waitFor(() => expect(api.listScanResources).toHaveBeenLastCalledWith("1", expect.stringContaining("resource_kind=document")));
  });

  it("lists rendered observations and links to exact evidence", async () => {
    api.getScan.mockResolvedValue({ ...scanFixture, rendered_attempted_count: 1, scope_config: { ...scanFixture.scope_config, render_mode: "starting_page" } });
    api.listScanRenderedObservations.mockResolvedValue({ items: [{
      id: 31, snapshot_id: 9, capture_state: "completed_with_warnings", static_final_url: "https://example.com/page", page_title: "Rendered Page", navigation_http_status: 200, duration_ms: 450, warning_count: 1, page_error_count: 0, blocked_request_count: 2, console_message_count: 1, has_viewport_screenshot: true, has_full_page_screenshot: false, has_rendered_dom: true, started_at: "2026-08-06T01:00:00Z", finished_at: "2026-08-06T01:00:01Z"
    }], total: 1, limit: 50, offset: 0 });
    renderRoute(<ScanDetailPage />, "/scans/:scanId", "/scans/1?tab=rendered");

    const link = await screen.findByRole("link", { name: "Open rendered evidence for https://example.com/page" });
    expect(screen.getAllByRole("navigation", { name: "rendered captures pagination" })).toHaveLength(2);
    expect(link).toHaveAttribute("href", "/scans/1/pages/9?tab=rendered");
    fireEvent.change(screen.getByLabelText("Rendered capture state"), { target: { value: "completed_with_warnings" } });
    await waitFor(() => expect(api.listScanRenderedObservations).toHaveBeenLastCalledWith("1", expect.stringContaining("capture_state=completed_with_warnings")));
  });

  it("distinguishes all rendered operational outcome buckets", async () => {
    api.getScan.mockResolvedValue({ ...scanFixture, scope_config: { ...scanFixture.scope_config, render_mode: "all_eligible" } });
    const renderedItem = (overrides: Record<string, unknown>) => ({
      id: 31, snapshot_id: 9, resource_id: 2, capture_state: "completed", static_final_url: "https://example.com/ok", browser_final_url: "https://example.com/ok", page_title: "Rendered Page", static_http_status: 200, navigation_http_status: 200, error_type: null, error_message: null, duration_ms: 450, warning_count: 0, page_error_count: 0, blocked_request_count: 0, console_message_count: 0, has_viewport_screenshot: true, has_full_page_screenshot: true, has_rendered_dom: true, finished_at: "2026-08-06T01:00:01Z", ...overrides
    });
    api.listScanRenderedObservations.mockResolvedValue({
      items: [
        renderedItem({}),
        renderedItem({ id: 32, snapshot_id: 10, static_final_url: "https://example.com/missing", navigation_http_status: 404, capture_state: "failed", error_type: "navigation_http_client_error", error_message: "Main-document navigation returned HTTP 404.", has_viewport_screenshot: false, has_full_page_screenshot: false, has_rendered_dom: false }),
        renderedItem({ id: 33, snapshot_id: 11, static_final_url: "https://example.com/limited", navigation_http_status: 429, capture_state: "failed", error_type: "navigation_rate_limited", error_message: "Main-document navigation was rate limited (HTTP 429).", has_viewport_screenshot: false, has_full_page_screenshot: false, has_rendered_dom: false }),
        renderedItem({ id: 34, snapshot_id: 12, static_final_url: "https://example.com/skipped", navigation_http_status: null, capture_state: "skipped", error_type: "host_rate_limit_circuit_open", error_message: "Browser capture was not attempted because repeated rate-limit responses opened the host render circuit.", has_viewport_screenshot: false, has_full_page_screenshot: false, has_rendered_dom: false }),
        renderedItem({ id: 35, snapshot_id: 13, static_final_url: "https://example.com/no-content", navigation_http_status: 204, capture_state: "failed", error_type: "navigation_no_content", error_message: "Main-document navigation returned HTTP 204 with no Page content.", has_viewport_screenshot: false, has_full_page_screenshot: false, has_rendered_dom: false }),
        renderedItem({ id: 36, snapshot_id: 14, static_final_url: "https://example.com/redirect", navigation_http_status: 302, capture_state: "failed", error_type: "navigation_http_redirect", error_message: "Main-document navigation ended at an unfollowed HTTP 302 response.", has_viewport_screenshot: false, has_full_page_screenshot: false, has_rendered_dom: false })
      ],
      total: 6,
      limit: 50,
      offset: 0,
      summary: { successful_renders: 1, no_content_responses: 1, redirect_responses: 1, http_error_responses: 1, rate_limited: 1, skipped_after_throttling: 1, technical_failures: 0, artifacts_retained: 3 }
    });

    renderRoute(<ScanDetailPage />, "/scans/:scanId", "/scans/1?tab=rendered");

    expect(await screen.findByRole("alert")).toHaveTextContent("Browser rendering was rate limited");
    expect(screen.getByRole("region", { name: "Rendered outcome summary" })).toHaveTextContent("Successful renders1");
    expect(screen.getByRole("region", { name: "Rendered outcome summary" })).toHaveTextContent("No-content responses1");
    expect(screen.getByRole("region", { name: "Rendered outcome summary" })).toHaveTextContent("HTTP redirects1");
    expect(screen.getByRole("region", { name: "Rendered outcome summary" })).toHaveTextContent("HTTP errors (not 429)1");
    expect(screen.getByText("HTTP error")).toBeInTheDocument();
    expect(screen.getByText("Rate limited", { selector: "span" })).toBeInTheDocument();
    expect(screen.getByText("No Page content")).toBeInTheDocument();
    expect(screen.getByText("HTTP redirect")).toBeInTheDocument();
    expect(screen.getByText("Not attempted - host throttled")).toBeInTheDocument();
    expect(screen.getAllByText("No artifacts")).toHaveLength(5);
    expect(screen.getByText("HTTP 404")).toBeInTheDocument();
    expect(screen.getByText("HTTP 429")).toBeInTheDocument();
  });

  it("distinguishes retry attempts from final failed pages", async () => {
    api.getScan.mockResolvedValue({
      ...scanFixture,
      failed_count: 0,
      static_request_attempt_count: 2,
      static_retry_request_count: 1,
      static_recovered_after_retry_count: 1,
      static_connection_timeout_count: 1
    });
    renderRoute(<ScanDetailPage />, "/scans/:scanId", "/scans/1");

    await screen.findByRole("heading", { name: "Static request attempts" });
    expect(screen.getByText("Final failed").parentElement).toHaveTextContent("0");
    expect(screen.getByText("Retry requests").parentElement).toHaveTextContent("1");
    expect(screen.getByText("Recovered").parentElement).toHaveTextContent("1");
    expect(screen.getByText("Connect timeouts").parentElement).toHaveTextContent("1");
  });

  it("shows retained static attempt evidence on the page observation", async () => {
    renderRoute(<PageDetailPage />, "/scans/:scanId/pages/:snapshotId", "/scans/1/pages/9");

    await screen.findByRole("heading", { name: "Static fetch attempts" });
    expect(await screen.findByText("Connection timed out")).toBeInTheDocument();
    expect(screen.getAllByText(/Connection Timeout/i).length).toBeGreaterThan(0);
    expect(screen.getByText("Succeeded")).toBeInTheDocument();
  });

  it("renders status badges, empty states, and URL-backed page filters", async () => {
    renderRoute(<ScanDetailPage />, "/scans/:scanId", "/scans/1?tab=pages");

    await screen.findByText("No pages recorded");
    expect(screen.getAllByRole("navigation", { name: "Pages pagination" })).toHaveLength(2);
    expect(screen.getByText("Completed")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Search pages"), { target: { value: "pricing" } });

    await waitFor(() => expect(api.listPages).toHaveBeenLastCalledWith("1", expect.stringContaining("search=pricing")));
  });

  it("keeps page-list pagination offset when search text has not changed", async () => {
    api.listPages.mockResolvedValue({
      items: [pageFixture],
      total: 75,
      limit: 50,
      offset: 0
    });
    renderRoute(<ScanDetailPage />, "/scans/:scanId", "/scans/1?tab=pages");

    fireEvent.click((await screen.findAllByRole("button", { name: "Next" }))[0]);

    await waitFor(() => expect(api.listPages).toHaveBeenLastCalledWith("1", expect.stringContaining("offset=50")));
    await new Promise((resolve) => window.setTimeout(resolve, 450));
    expect(api.listPages).toHaveBeenLastCalledWith("1", expect.stringContaining("offset=50"));
  });

  it("opens graph tab, filters, selects a node, inspects an edge, and toggles presentation", async () => {
    renderRoute(<ScanDetailPage />, "/scans/:scanId", "/scans/1?tab=graph&selected_edge=8-2");

    expect(await screen.findByText("Website topology graph")).toBeInTheDocument();
    expect(await screen.findByText(/2 of 2 nodes/i)).toBeInTheDocument();
    expect(await screen.findByText("Selected edge")).toBeInTheDocument();
    expect(await screen.findByText("Pricing link")).toBeInTheDocument();
    expect(api.getScanDeletePreview).not.toHaveBeenCalled();

    fireEvent.change(screen.getByLabelText("Graph mode"), { target: { value: "2d" } });
    expect(screen.getByLabelText("Graph mode")).toHaveValue("2d");

    fireEvent.change(screen.getByLabelText("Graph mode"), { target: { value: "3d" } });
    await waitFor(() => {
      expect(api.getScanGraph.mock.calls.some((call) => call[0] === "1" && String(call[1]).includes("max_nodes=100") && String(call[1]).includes("max_edges=250"))).toBe(true);
    });
    expect(screen.getByLabelText("Graph mode")).toHaveValue("3d");

    fireEvent.change(screen.getByLabelText("Search graph nodes"), { target: { value: "pricing" } });
    await waitFor(() => expect(screen.getAllByText("Pricing").length).toBeGreaterThan(0));
    fireEvent.click(screen.getAllByText("Pricing")[0]);
    expect(await screen.findByText("Selected page")).toBeInTheDocument();
    expect(screen.getByText(/Inbound: 2 occurrences/i)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Neighborhood" }));
    await waitFor(() => expect(api.getScanGraph).toHaveBeenLastCalledWith("1", expect.stringContaining("focus_snapshot_id=9")));

    fireEvent.change(screen.getByLabelText("Graph status filter"), { target: { value: "2xx" } });
    await waitFor(() => expect(api.getScanGraph).toHaveBeenLastCalledWith("1", expect.stringContaining("status=2xx")));

    fireEvent.click(screen.getByRole("button", { name: "Presentation" }));
    expect(await screen.findByRole("button", { name: "Exit presentation" })).toBeInTheDocument();
  });

  it("renders a scan status badge with accessible text", () => {
    render(<StatusBadge status="completed_with_errors" />);
    expect(screen.getByText("Completed With Errors")).toBeInTheDocument();
  });
});

describe("saved sites workflow", () => {
  it("renders sites list filters and actions", async () => {
    renderRoute(<SitesPage />, "/sites", "/sites");

    expect(await screen.findByRole("heading", { name: "Saved sites" })).toBeInTheDocument();
    expect(await screen.findByText("Example Site")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Search sites"), { target: { value: "example" } });

    await waitFor(() => expect(api.listSites).toHaveBeenLastCalledWith(expect.stringContaining("search=example")));
  });

  it("creates a site with saved scope and one value per line", async () => {
    renderRoute(<SiteFormPage mode="create" />, "/sites/new", "/sites/new");

    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Example Site" } });
    fireEvent.change(screen.getByLabelText("Base URL"), { target: { value: "https://example.com/learn/" } });
    fireEvent.change(screen.getByLabelText("Included path prefixes"), { target: { value: "/learn/\n/docs/" } });
    fireEvent.click(screen.getByRole("button", { name: "Create site" }));

    await waitFor(() => expect(api.createSite).toHaveBeenCalledTimes(1));
    expect(api.createSite.mock.calls[0][0].scope_config.included_path_prefixes).toEqual(["/learn/", "/docs/"]);
  });

  it("blocks saving site settings with invalid numeric scope", async () => {
    renderRoute(<SiteFormPage mode="edit" />, "/sites/:siteId/edit", "/sites/3/edit");

    expect(await screen.findByRole("heading", { name: "Edit site" })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Maximum pages"), { target: { value: "" } });

    expect(screen.getByText(/Maximum pages must be between/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save site" })).toBeDisabled();
  });

  it("renders site details and can disable a site", async () => {
    renderRoute(<SiteDetailPage />, "/sites/:siteId", "/sites/3");

    expect(await screen.findByRole("heading", { name: "Example Site" })).toBeInTheDocument();
    expect(screen.getByText("Recent scans")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Disable" }));

    await waitFor(() => expect(api.updateSite).toHaveBeenCalledWith("3", { is_active: false }));
  });

  it("starts a saved-site scan with scan-specific overrides", async () => {
    renderRoute(<NewScanPage />, "/scans/new", "/scans/new?site_id=3");

    expect(await screen.findByLabelText("Site")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Maximum pages"), { target: { value: "7" } });
    fireEvent.click(screen.getByRole("button", { name: "Start scan" }));

    await waitFor(() => expect(api.createSiteScan).toHaveBeenCalledWith("3", expect.objectContaining({ max_pages: 7 }), false, []));
    expect(api.updateSite).not.toHaveBeenCalled();
  });

  it("selects all URL inventory sources for a saved-site scan", async () => {
    renderRoute(<NewScanPage />, "/scans/new", "/scans/new?site_id=3");

    expect(await screen.findByLabelText("Site")).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("Include current URL inventory"));

    const selectAll = await screen.findByLabelText("Select all sources");
    await waitFor(() => expect(selectAll).toBeChecked());
    fireEvent.click(selectAll);

    expect(screen.getByText("Select at least one source, or turn off inventory.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Start scan" })).toBeDisabled();

    fireEvent.click(selectAll);
    fireEvent.click(screen.getByRole("button", { name: "Start scan" }));

    await waitFor(() => expect(api.createSiteScan).toHaveBeenCalledWith("3", expect.any(Object), true, [4]));
  });

  it("shows source and inventory tools on site detail", async () => {
    renderRoute(<SiteDetailPage />, "/sites/:siteId", "/sites/3?tab=sources");

    expect(await screen.findByText("Sources")).toBeInTheDocument();
    expect(await screen.findByText("Main sitemap")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    await waitFor(() => expect(api.refreshSource).toHaveBeenCalledWith("3", "4"));

    fireEvent.click(screen.getByRole("button", { name: /inventory/i }));
    expect(await screen.findByText("https://example.com/a")).toBeInTheDocument();
  });

  it("selects Sources for one bounded bulk refresh", async () => {
    api.listSources.mockResolvedValue({
      items: [
        sourceFixture,
        {
          ...sourceFixture,
          id: 7,
          name: "Secondary sitemap",
          source_url: "https://example.com/secondary.xml",
          normalized_source_url: "https://example.com/secondary.xml",
        },
      ],
      total: 2,
      limit: 100,
      offset: 0,
    });
    renderRoute(<SiteDetailPage />, "/sites/:siteId", "/sites/3?tab=sources");

    const selectAll = await screen.findByLabelText(
      "Select all refreshable Sources on this loaded page",
    );
    fireEvent.click(selectAll);
    expect(screen.getByText("2 Sources selected")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Refresh selected" }));

    await waitFor(() =>
      expect(api.bulkRefreshSources).toHaveBeenCalledWith("3", [4, 7]),
    );
  });

  it("replaces a stale queued Source status when its job is terminal", async () => {
    api.listSources
      .mockResolvedValueOnce({
        items: [{ ...sourceFixture, last_refresh_status: "queued" }],
        total: 1,
        limit: 100,
        offset: 0,
      })
      .mockResolvedValue({
        items: [sourceFixture],
        total: 1,
        limit: 100,
        offset: 0,
      });
    api.listJobs.mockResolvedValue({
      items: [
        {
          ...jobFixture,
          id: 12,
          job_type: "source_refresh",
          source_refresh_id: 5,
          website_property_id: 3,
          payload_json: { source_id: 4, source_refresh_id: 5 },
        },
      ],
      total: 1,
      limit: 100,
      offset: 0,
    });

    renderRoute(<SiteDetailPage />, "/sites/:siteId", "/sites/3?tab=sources");

    await waitFor(() => expect(api.listSources.mock.calls.length).toBeGreaterThan(1));
    expect(await screen.findByText("Completed")).toBeInTheDocument();
    expect(screen.queryByText("Queued")).not.toBeInTheDocument();
  });

  it("shows persistent site pages and observation history", async () => {
    renderRoute(<SiteDetailPage />, "/sites/:siteId", "/sites/3?tab=pages");

    expect(await screen.findByText("https://example.com/page")).toBeInTheDocument();
    expect(screen.getAllByRole("navigation", { name: "Pages pagination" })).toHaveLength(2);
    expect(screen.getByText("Observed Page")).toBeInTheDocument();
    expect(api.listSitePages).toHaveBeenCalledWith("3", expect.stringContaining(""));

    cleanup();
    renderRoute(<PersistentPageDetailPage />, "/sites/:siteId/pages/:resourceId", "/sites/3/pages/2");

    expect(await screen.findByRole("tab", { name: /Scans/ })).toBeInTheDocument();
    expect(screen.queryByText(/Retry Page/i)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: /Scans/ }));
    await waitFor(() => expect(screen.getAllByText("Revalidated unchanged").length).toBeGreaterThan(0));
    expect(screen.getByRole("link", { name: "Open Observation" })).toBeInTheDocument();
  });

  it("deletes a Page workspace from Page detail and returns to the list", async () => {
    renderRoute(<PersistentPageDetailPage />, "/sites/:siteId/pages/:resourceId", "/sites/3/pages/2");

    fireEvent.click(await screen.findByRole("button", { name: "Delete Page" }));
    expect(screen.getByRole("dialog", { name: "Delete this Page workspace?" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Delete Page workspace" }));
    await waitFor(() => expect(api.bulkDeletePages).toHaveBeenCalledWith("3", [2]));
    await waitFor(() => expect(screen.queryByRole("button", { name: "Delete Page" })).not.toBeInTheDocument());
  });

  it("deletes Page workspaces and current Inventory entries through accessible confirmations", async () => {
    renderRoute(<SiteDetailPage />, "/sites/:siteId", "/sites/3?tab=pages");

    fireEvent.click(await screen.findByRole("button", { name: "Delete" }));
    expect(screen.getByRole("dialog", { name: "Delete this Page workspace?" })).toBeInTheDocument();
    expect(screen.getAllByText(/Historical Scan evidence will remain/).length).toBeGreaterThan(0);
    fireEvent.click(screen.getByRole("button", { name: "Delete Page workspace" }));
    await waitFor(() => expect(api.bulkDeletePages).toHaveBeenCalledWith("3", [2]));

    cleanup();
    renderRoute(<SiteDetailPage />, "/sites/:siteId", "/sites/3?tab=inventory");
    fireEvent.click(await screen.findByRole("button", { name: "Delete" }));
    expect(screen.getByRole("dialog", { name: "Delete this URL from current Inventory?" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Delete from current Inventory" }));
    await waitFor(() => expect(api.bulkDeleteInventoryEntries).toHaveBeenCalledWith("3", [6]));
  });

  it("uses independent Page and Inventory state filters", async () => {
    renderRoute(<SiteDetailPage />, "/sites/:siteId", "/sites/3?tab=pages");
    fireEvent.change(await screen.findByLabelText("Site Page state"), { target: { value: "suppressed" } });
    await waitFor(() => expect(api.listSitePages).toHaveBeenLastCalledWith("3", expect.stringContaining("workspace_state=suppressed")));

    cleanup();
    renderRoute(<SiteDetailPage />, "/sites/:siteId", "/sites/3?tab=inventory");
    fireEvent.change(await screen.findByLabelText("Inventory visibility"), { target: { value: "suppressed" } });
    await waitFor(() => expect(api.listInventory).toHaveBeenLastCalledWith("3", expect.stringContaining("visibility=suppressed")));
  });

  it("partitions mixed Page bulk lifecycle actions by workspace state", async () => {
    api.listSitePages.mockResolvedValue({
      items: [
        persistentPageFixture,
        {
          ...persistentPageFixture,
          site_page_id: 13,
          resource_id: 3,
          normalized_url: "https://example.com/removed",
          workspace_state: "suppressed",
          suppressed_at: "2026-08-25T00:00:00Z",
        },
      ],
      total: 2,
      limit: 50,
      offset: 0,
    });
    renderRoute(<SiteDetailPage />, "/sites/:siteId", "/sites/3?tab=pages&workspace_state=all");

    fireEvent.click(await screen.findByLabelText("Select https://example.com/page"));
    fireEvent.click(screen.getByLabelText("Select https://example.com/removed"));
    expect(screen.getByRole("button", { name: "Remove 1 active Page" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Restore 1 removed Page" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Delete 2 selected Pages" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Remove 1 active Page" }));
    fireEvent.click(screen.getByRole("button", { name: "Remove from Site Pages" }));
    await waitFor(() =>
      expect(api.bulkPageWorkspaceState).toHaveBeenCalledWith("3", [2], "suppressed"),
    );
  });

  it("clears loaded-page selections whenever Page or Inventory query identity changes", async () => {
    renderRoute(<SiteDetailPage />, "/sites/:siteId", "/sites/3?tab=pages");
    fireEvent.click(await screen.findByLabelText("Select https://example.com/page"));
    expect(screen.getByText("1 selected on this page")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Search site pages"), { target: { value: "other" } });
    await waitFor(() => expect(screen.queryByText("1 selected on this page")).not.toBeInTheDocument());

    cleanup();
    renderRoute(<SiteDetailPage />, "/sites/:siteId", "/sites/3?tab=inventory");
    fireEvent.click(await screen.findByLabelText("Select https://example.com/a"));
    expect(screen.getByText("1 URL selected")).toBeInTheDocument();
    fireEvent.change(screen.getAllByLabelText("inventory URL rows per page")[0], { target: { value: "100" } });
    await waitFor(() => expect(screen.queryByText("1 URL selected")).not.toBeInTheDocument());
  });

  it("selects Inventory rows for grouped bulk delete and restores suppressions", async () => {
    renderRoute(<SiteDetailPage />, "/sites/:siteId", "/sites/3?tab=inventory");

    fireEvent.click(await screen.findByLabelText("Select https://example.com/a"));
    fireEvent.click(screen.getByRole("button", { name: "Delete selected" }));
    expect(screen.getByRole("dialog", { name: "Delete 1 selected URL from current Inventory?" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Delete from current Inventory" }));
    await waitFor(() =>
      expect(api.bulkDeleteInventoryEntries).toHaveBeenCalledWith("3", [6]),
    );

    cleanup();
    api.listInventory.mockResolvedValue({
      items: [{
        ...inventoryFixture,
        suppression_id: 15,
        is_suppressed: true,
        suppressed_at: "2026-08-25T00:00:00Z",
      }],
      total: 1,
      limit: 50,
      offset: 0,
    });
    renderRoute(
      <SiteDetailPage />,
      "/sites/:siteId",
      "/sites/3?tab=inventory&visibility=suppressed",
    );
    fireEvent.click(await screen.findByLabelText("Select https://example.com/a"));
    fireEvent.click(screen.getByRole("button", { name: "Restore selected" }));
    fireEvent.click(screen.getByRole("button", { name: "Restore to Inventory" }));
    await waitFor(() =>
      expect(api.bulkRestoreInventorySuppressions).toHaveBeenCalledWith("3", [15]),
    );
  });

  it("partitions mixed Inventory bulk actions and sends one representative per URL", async () => {
    api.listInventory.mockResolvedValue({
      items: [
        inventoryFixture,
        {
          ...inventoryFixture,
          normalized_url: "https://example.com/removed",
          resource_id: 3,
          sources: [
            { id: 9, name: "Secondary sitemap", type: "sitemap", entry_id: 16, raw_url: "https://example.com/removed" },
            { id: 10, name: "Secondary manual", type: "manual", entry_id: 18, raw_url: "/removed" },
          ],
          suppression_id: 17,
          is_suppressed: true,
          suppressed_at: "2026-08-25T00:00:00Z",
        },
      ],
      total: 2,
      limit: 50,
      offset: 0,
    });
    renderRoute(<SiteDetailPage />, "/sites/:siteId", "/sites/3?tab=inventory&visibility=all");

    fireEvent.click(await screen.findByLabelText("Select https://example.com/a"));
    fireEvent.click(screen.getByLabelText("Select https://example.com/removed"));
    expect(screen.getByRole("button", { name: "Remove 1 active URL" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Restore 1 removed URL" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Delete 2 selected URLs" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Delete 2 selected URLs" }));
    fireEvent.click(screen.getByRole("button", { name: "Delete from current Inventory" }));
    await waitFor(() =>
      expect(api.bulkDeleteInventoryEntries).toHaveBeenCalledWith("3", [6, 16]),
    );
  });

  it("blocks saved-site scans with invalid scan-specific numeric overrides", async () => {
    renderRoute(<NewScanPage />, "/scans/new", "/scans/new?site_id=3");

    expect(await screen.findByLabelText("Site")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Maximum pages"), { target: { value: "" } });

    expect(screen.getByText(/Maximum pages must be between/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Start scan" })).toBeDisabled();
  });
});

describe("scan history workflow", () => {
  it("renders all scans, preserves filters in the URL, and opens delete confirmation", async () => {
    renderRoute(<ScansPage />, "/scans", "/scans");

    expect(await screen.findByRole("heading", { name: "All scans" })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Search scans"), { target: { value: "example" } });
    fireEvent.change(screen.getByLabelText("Scan status"), { target: { value: "completed" } });

    await waitFor(() => expect(api.listScanHistory).toHaveBeenLastCalledWith(expect.stringContaining("search=example")));
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));

    expect(await screen.findByRole("dialog", { name: "Delete this scan?" })).toBeInTheDocument();
    expect(screen.getByText(/Estimated storage reclaimed/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Delete scan" }));
    await waitFor(() => expect(api.deleteScan).toHaveBeenCalledWith("1"));
  });
});

describe("page detail workflow", () => {
  it("keeps the associated Site Page workspace action visible across observation tabs", async () => {
    api.getSnapshot.mockResolvedValue({
      ...snapshotFixture,
      website_property_id: 3,
      website_property_name: "Example Site",
      site_page_id: 12,
      has_persistent_page: true,
      is_html_page: true,
    });
    api.getRenderedObservation.mockResolvedValue(renderedObservationFixture);
    renderRoute(<PageDetailPage />, "/scans/:scanId/pages/:snapshotId", "/scans/1/pages/9");

    const actionName = "Open Page workspace for Example page";
    const action = await screen.findByRole("link", { name: actionName });
    expect(action).toHaveAttribute("href", "/sites/3/pages/2");
    expect(screen.getByText("Example Site")).toBeInTheDocument();
    expect(screen.getByText(/This observation records what Site Ledger found/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Back to Scan Pages" })).toBeInTheDocument();
    expect(screen.getByTestId("observation-header-actions")).toHaveClass("flex-wrap");

    for (const tabName of ["Head", "Outgoing links", "Inbound links", "HTML", "Rendered"]) {
      fireEvent.click(screen.getByRole("tab", { name: new RegExp(tabName, "i") }));
      expect(screen.getByRole("link", { name: actionName })).toHaveAttribute("href", "/sites/3/pages/2");
    }
  });

  it("explains ad hoc and missing legacy Page workspace associations", async () => {
    renderRoute(<PageDetailPage />, "/scans/:scanId/pages/:snapshotId", "/scans/1/pages/9");
    expect(await screen.findByText(/ad hoc Scan and has no Site-scoped Page workspace/)).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Open Page workspace/ })).not.toBeInTheDocument();

    cleanup();
    api.getSnapshot.mockResolvedValue({
      ...snapshotFixture,
      website_property_id: 8,
      website_property_name: "Legacy Site",
      site_page_id: null,
      has_persistent_page: false,
    });
    renderRoute(<PageDetailPage />, "/scans/:scanId/pages/:snapshotId", "/scans/1/pages/9");
    expect(await screen.findByText(/persistent Page workspace association is unavailable/)).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Open Page workspace/ })).not.toBeInTheDocument();
  });

  it("does not offer a Page workspace for a non-HTML Resource observation", async () => {
    api.getSnapshot.mockResolvedValue({
      ...snapshotFixture,
      content_type: "application/pdf",
      representation_kind: "document",
      website_property_id: 3,
      website_property_name: "Example Site",
      site_page_id: 12,
      has_persistent_page: false,
      is_html_page: false,
    });
    renderRoute(<PageDetailPage />, "/scans/:scanId/pages/:snapshotId", "/scans/1/pages/9");
    expect(await screen.findByText(/non-HTML Resource and does not have a Page workspace/)).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Open Page workspace/ })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open live Resource" })).toBeInTheDocument();
  });

  it("renders redirect chains as ordered fields", async () => {
    renderRoute(<PageDetailPage />, "/scans/:scanId/pages/:snapshotId", "/scans/1/pages/9");

    expect(await screen.findByText("Redirect chain")).toBeInTheDocument();
    expect(screen.getByText("Hop 1")).toBeInTheDocument();
    expect(screen.getAllByText("https://example.com/new").length).toBeGreaterThan(0);
  });

  it("renders head metadata sections instead of only raw JSON", async () => {
    renderRoute(<PageDetailPage />, "/scans/:scanId/pages/:snapshotId", "/scans/1/pages/9");

    fireEvent.click(await screen.findByRole("tab", { name: "Head" }));

    expect(screen.getByText("Basic metadata")).toBeInTheDocument();
    expect(screen.getByText("Open Graph")).toBeInTheDocument();
    expect(screen.getByText("Structured data")).toBeInTheDocument();
  });

  it("renders individual link occurrences with provenance fields", async () => {
    renderRoute(<PageDetailPage />, "/scans/:scanId/pages/:snapshotId", "/scans/1/pages/9");

    fireEvent.click(await screen.findByRole("tab", { name: /Outgoing links/i }));

    expect((await screen.findAllByText("External")).length).toBeGreaterThan(0);
    expect(screen.getByText("No visible text")).toBeInTheDocument();
    expect(screen.getByText(/aria-label:/)).toBeInTheDocument();
    expect(document.body.textContent).toContain("Download Snagit");
  });

  it("renders inbound link occurrences with scan-specific summary", async () => {
    renderRoute(<PageDetailPage />, "/scans/:scanId/pages/:snapshotId", "/scans/1/pages/9");

    fireEvent.click(await screen.findByRole("tab", { name: /Inbound links/i }));

    expect(await screen.findByText("Inbound link summary")).toBeInTheDocument();
    expect(screen.getByText("Unique source pages")).toBeInTheDocument();
    expect(screen.getByText("Self link")).toBeInTheDocument();
    expect(document.body.textContent).toContain("Source page");
    fireEvent.change(screen.getByLabelText("Search inbound links"), { target: { value: "source" } });
    await waitFor(() => expect(api.getInboundLinks).toHaveBeenLastCalledWith("9", expect.stringContaining("search=source")));
  });

  it("shows raw HTML as escaped text without executing it", async () => {
    renderRoute(<PageDetailPage />, "/scans/:scanId/pages/:snapshotId", "/scans/1/pages/9");

    fireEvent.click(await screen.findByRole("tab", { name: "HTML" }));

    await screen.findByLabelText("Escaped HTML source");
    expect(screen.getByLabelText("Escaped HTML source").textContent).toContain("window.executed = true");
    expect((window as unknown as { executed?: boolean }).executed).toBeUndefined();
  });

  it("inspects a browser-rendered observation without executing its DOM", async () => {
    api.getRenderedObservation.mockResolvedValue(renderedObservationFixture);
    renderRoute(<PageDetailPage />, "/scans/:scanId/pages/:snapshotId", "/scans/1/pages/9");
    fireEvent.click(await screen.findByRole("tab", { name: "Rendered" }));
    expect(await screen.findByText(/chromium 151/i)).toBeInTheDocument();
    expect(screen.getByText("1440 x 900 @ 1")).toBeInTheDocument();
  });
});

describe("shared UX utilities", () => {
  it("formats API unavailable errors for users", () => {
    expect(displayError(new TypeError("Failed to fetch")).message).toMatch(/Site Ledger API could not be reached/i);
  });

  it("copies values with feedback", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });
    render(<CopyButton value="https://example.com/" />);

    fireEvent.click(screen.getByRole("button", { name: "Copy" }));

    await waitFor(() => expect(writeText).toHaveBeenCalledWith("https://example.com/"));
    expect(screen.getByRole("button", { name: "Copy copied" })).toBeInTheDocument();
  });
});

function renderRoute(element: React.ReactElement, path: string, initialEntry = path) {
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })}>
      <MemoryRouter initialEntries={[initialEntry]}>
        <Routes>
          <Route path={path} element={element} />
          <Route path="*" element={<div />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  );
}

function renderShell(initialEntry: string) {
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })}>
      <MemoryRouter initialEntries={[initialEntry]}>
        <Routes>
          <Route path="/" element={<AppShell />}>
            <Route path="scans/new" element={<NewScanPage />} />
          </Route>
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  );
}

function resourceFixture(overrides: Partial<ResourceInventoryItem>): ResourceInventoryItem {
  return {
    resource_id: 1,
    normalized_url: "https://example.com/resource",
    host: "example.com",
    path: "/resource",
    file_extension: null,
    effective_kind: "other",
    effective_kind_label: "Other",
    classification_source: "extension",
    observed: false,
    discovered_only: true,
    snapshot_id: null,
    final_url: null,
    http_status: null,
    normalized_mime_type: null,
    content_disposition_filename: null,
    declared_content_length: null,
    network_bytes_transferred: null,
    fetched_at: null,
    response_time_ms: null,
    occurrence_count: 1,
    source_page_count: 1,
    anchor_occurrence_count: 0,
    embedded_occurrence_count: 1,
    in_scope_occurrence_count: 1,
    out_of_scope_occurrence_count: 0,
    first_discovered_at: "2026-08-06T01:00:00Z",
    latest_discovered_at: "2026-08-06T01:00:00Z",
    observation_count: 0,
    scan_count: 1,
    ...overrides
  };
}

const scanFixture: Scan = {
  id: 1,
  website_property_id: null,
  website_property_name: null,
  website_property_base_url: null,
  starting_url: "https://example.com/",
  status: "completed",
  scope_config: {
    allowed_host_patterns: [],
    excluded_host_patterns: [],
    included_path_prefixes: ["/"],
    excluded_path_prefixes: ["/wp-admin/", "/wp-login.php"],
    follow_subdomains: false,
    max_pages: 100,
    max_depth: 3,
    respect_robots_txt: false,
    request_timeout_seconds: 10,
    static_max_attempts: 2,
    static_retry_initial_delay_ms: 500,
    static_retry_max_delay_ms: 5000,
    max_html_response_bytes: 2000000,
    concurrent_requests_per_host: 2,
    delay_between_requests_ms: 0,
    user_agent: "WebsiteScanner/0.1",
    drop_query_parameters: ["utm_*", "gclid", "fbclid", "msclkid"],
    allow_private_networks: false,
    max_redirects: 10,
    enable_http_revalidation: true,
    enable_parse_reuse: true,
    render_mode: "none", render_max_pages: 10, render_viewport_width: 1440, render_viewport_height: 900,
    render_device_scale_factor: 1, render_locale: "en-US", render_timezone: "UTC", render_color_scheme: "light",
    render_reduced_motion: "reduce", render_navigation_timeout_seconds: 30, render_load_timeout_seconds: 10,
    render_capture_full_page: true, render_max_full_page_height: 20000, render_max_dom_bytes: 5000000,
    render_max_screenshot_bytes: 15000000, render_max_network_entries: 1000, render_max_console_entries: 200,
    render_max_page_errors: 50, render_max_page_duration_seconds: 60, render_max_total_network_bytes: 50000000,
    render_max_resource_bytes: 10000000
  },
  created_at: "2026-07-30T01:00:00Z",
  started_at: "2026-07-30T01:00:01Z",
  finished_at: "2026-07-30T01:00:03Z",
  discovered_count: 1,
  fetched_count: 1,
  failed_count: 0,
  skipped_count: 0,
  queued_count: 0,
  conditional_request_count: 0,
  not_modified_count: 0,
  parse_reuse_count: 0,
  full_parse_count: 1,
  network_bytes_transferred: 1200,
  reused_content_bytes: 0,
  rendered_selected_count: 0,
  rendered_attempted_count: 0,
  rendered_completed_count: 0,
  rendered_failed_count: 0,
  rendered_skipped_count: 0,
  rendered_blocked_request_count: 0,
  rendered_artifact_count: 0,
  static_request_attempt_count: 1,
  static_retry_request_count: 0,
  static_recovered_after_retry_count: 0,
  static_retry_exhausted_count: 0,
  static_connection_timeout_count: 0,
  static_read_timeout_count: 0,
  static_connection_error_count: 0,
  stop_reason: "max_pages",
  fatal_error_message: null
};

const emptyPageList: PageList = {
  items: [],
  total: 0,
  limit: 50,
  offset: 0
};

const pageFixture = {
  id: 9,
  resource_id: 2,
  requested_url: "https://example.com/page",
  final_url: "https://example.com/page",
  http_status: 200,
  title: "Example page",
  depth: 1,
  content_type: "text/html",
  discovery_source: "https://example.com/",
  inbound_occurrence_count: 1,
  inbound_source_page_count: 1,
  response_time_ms: 50,
  fetch_state: "fetched",
  error_type: null,
  retrieval_method: "full_fetch",
  parse_method: "parsed",
  retrieval_http_status: 200,
  reused_from_snapshot_id: null,
  network_bytes_transferred: 1200
};

const snapshotFixture: Snapshot = {
  id: 9,
  scan_id: 1,
  resource_id: 2,
  requested_url: "https://example.com/old",
  final_url: "https://example.com/new",
  http_status: 200,
  content_type: "text/html",
  encoding: "utf-8",
  crawl_depth: 1,
  fetched_at: "2026-07-30T01:00:02Z",
  response_time_ms: 123,
  response_headers: {},
  redirect_chain: [{ requested_url: "https://example.com/old", status_code: 301, location: "/new", resolved_url: "https://example.com/new" }],
  html_raw_byte_size: 1200,
  html_stored_byte_size: 500,
  raw_html_sha256: "rawhash",
  head_sha256: "headhash",
  page_title: "Example page",
  html_language: "en",
  meta_description: "Description",
  meta_robots: "index,follow",
  canonical_url: "https://example.com/new",
  parsed_head_json: {
    encoding: "utf-8",
    viewport: "width=device-width, initial-scale=1",
    open_graph: { "og:title": "OG title" },
    twitter: { "twitter:card": "summary" },
    meta: [{ name: "description", content: "Description" }],
    links: [{ rel: "canonical", href: "https://example.com/new" }],
    json_ld: ['{"@context":"https://schema.org","@type":"WebPage"}']
  },
  fetch_state: "fetched",
  error_type: null,
  error_message: null,
  parse_artifact_id: 3,
  reused_from_snapshot_id: null,
  retrieval_method: "full_fetch",
  parse_method: "parsed",
  retrieval_http_status: 200,
  retrieval_response_headers: {},
  network_bytes_transferred: 1200,
  request_variant_fingerprint: "fingerprint",
  etag: '"abc"',
  last_modified: "Wed, 05 Aug 2026 00:00:00 GMT",
  cache_control: null,
  vary_header: null,
  website_property_id: null,
  website_property_name: null,
  site_page_id: null,
  has_persistent_page: false,
  is_html_page: true
};

const renderedObservationFixture = {
  id: 7, snapshot_id: 9, capture_state: "completed", started_at: "2026-08-06T01:00:00Z", finished_at: "2026-08-06T01:00:01Z",
  requested_url: "https://example.com/", final_url: "https://example.com/", navigation_http_status: 200, document_title: "Rendered",
  browser_engine: "chromium", browser_version: "151", playwright_version: "1.62", renderer_version: "1", browser_policy_version: "1", capture_schema_version: "1",
  user_agent: "Chromium", viewport_width: 1440, viewport_height: 900, device_scale_factor: 1, locale: "en-US", timezone_id: "UTC", color_scheme: "light", reduced_motion: "reduce",
  readiness_state: "load", load_event_reached: true, fonts_ready_reached: true, duration_ms: 500, configuration_fingerprint: "a".repeat(64), network_entry_count: 1,
  blocked_request_count: 0, console_message_count: 0, page_error_count: 0, warning_count: 0, network_truncated: false, console_truncated: false,
  page_errors_truncated: false, total_encoded_network_bytes: 1200, error_type: null, error_message: null, warnings_json: [], artifacts: []
};

const linkFixtures = [
  {
    id: 1,
    raw_href: "/download",
    resolved_url: "https://example.com/download",
    normalized_target_url: "https://example.com/download",
    target_resource_id: null,
    anchor_text: null,
    title: "Download",
    aria_label: "Download Snagit",
    rel: "nofollow",
    target: "_blank",
    dom_path: "html > body > a",
    in_scope: false,
    scope_decision: "external",
    exclusion_reason: "External host",
    discovered_at: "2026-07-30T01:00:02Z"
  }
];

const inboundFixture = {
  items: [
    {
      ...linkFixtures[0],
      source_snapshot_id: 8,
      source_resource_id: 3,
      source_requested_url: "https://example.com/source",
      source_final_url: "https://example.com/source",
      source_page_title: "Source page",
      source_http_status: 200,
      source_fetch_state: "fetched",
      source_crawl_depth: 0,
      is_self_link: true
    }
  ],
  total: 1,
  limit: 50,
  offset: 0,
  summary: {
    total_occurrences: 1,
    unique_source_pages: 1,
    unique_anchor_texts: 0,
    nofollow_occurrences: 1,
    self_link_occurrences: 1
  }
};

const graphFixture = {
  scan: {
    id: 1,
    starting_url: "https://example.com/",
    status: "completed",
    website_property_id: null,
    website_property_name: null,
    created_at: "2026-07-30T01:00:00Z",
    finished_at: "2026-07-30T01:01:00Z"
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
    total_occurrences: 2,
    truncated: false,
    truncation_reasons: [],
    focused: false,
    focus_snapshot_id: null,
    focus_hops: null
  },
  nodes: [
    {
      id: "snapshot:8",
      kind: "page",
      snapshot_id: 8,
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
      response_time_ms: 80,
      inbound_occurrence_count: 0,
      inbound_source_page_count: 0,
      outbound_occurrence_count: 2,
      outbound_target_page_count: 1,
      is_scan_seed: true,
      seed_origin_count: 1,
      is_starting_url: true,
      redirects: false,
      canonical_url: null,
      category: "2xx"
    },
    {
      id: "snapshot:9",
      kind: "page",
      snapshot_id: 9,
      resource_id: 2,
      requested_url: "https://example.com/pricing",
      final_url: "https://example.com/pricing",
      page_title: "Pricing",
      host: "example.com",
      path: "/pricing",
      http_status: 200,
      fetch_state: "fetched",
      error_type: null,
      crawl_depth: 1,
      content_type: "text/html",
      response_time_ms: 120,
      inbound_occurrence_count: 2,
      inbound_source_page_count: 1,
      outbound_occurrence_count: 0,
      outbound_target_page_count: 0,
      is_scan_seed: false,
      seed_origin_count: 0,
      is_starting_url: false,
      redirects: false,
      canonical_url: null,
      category: "2xx"
    }
  ],
  edges: [
    {
      id: "8-2",
      source: "snapshot:8",
      target: "snapshot:9",
      source_snapshot_id: 8,
      target_snapshot_id: 9,
      target_resource_id: 2,
      occurrence_count: 2,
      unique_anchor_text_count: 1,
      nofollow_occurrence_count: 0,
      follow_occurrence_count: 2,
      empty_anchor_occurrence_count: 0,
      is_self_link: false,
      sample_anchor_texts: ["Pricing"],
      first_discovered_at: "2026-07-30T01:00:01Z",
      last_discovered_at: "2026-07-30T01:00:02Z",
      scope_decisions: { crawlable: 2 },
      dom_regions: { main: 2 }
    }
  ],
  effective_filters: {}
};

const graphCapabilitiesFixture = {
  default_node_limit: 100,
  maximum_node_limit: 3000,
  default_edge_limit: 250,
  maximum_edge_limit: 10000,
  default_focus_hops: 1,
  maximum_focus_hops: 3,
  sample_anchor_limit: 5,
  occurrence_page_default: 50,
  occurrence_page_maximum: 200,
  supported_status_filters: ["any", "2xx", "3xx", "4xx", "5xx", "none"],
  supported_error_filters: ["any", "with_errors", "without_errors"],
  supported_node_size_modes: ["uniform", "inbound_sources", "inbound_occurrences", "outbound_targets", "outbound_occurrences", "response_time", "depth_inverse"],
  supported_node_category_modes: ["status", "fetch_state", "depth", "host", "path", "error", "seed"]
};

const edgeOccurrenceFixture = {
  items: [
    {
      ...linkFixtures[0],
      id: 20,
      source_snapshot_id: 8,
      target_snapshot_id: 9,
      anchor_text: "Pricing link",
      raw_href: "/pricing",
      is_self_link: false
    }
  ],
  total: 2,
  limit: 50,
  offset: 0,
  edge: graphFixture.edges[0]
};

const siteFixture = {
  id: 3,
  name: "Example Site",
  base_url: "https://example.com/",
  normalized_base_url: "https://example.com/",
  description: "A site",
  group_key: "Marketing",
  locale: "en-US",
  platform_key: "WordPress Root",
  ownership_key: "Web Team",
  scope_config: {
    allowed_host_patterns: ["example.com"],
    excluded_host_patterns: [],
    included_path_prefixes: ["/"],
    excluded_path_prefixes: ["/wp-admin/", "/wp-login.php"],
    follow_subdomains: false,
    max_pages: 100,
    max_depth: 3,
    respect_robots_txt: false,
    request_timeout_seconds: 10,
    static_max_attempts: 2,
    static_retry_initial_delay_ms: 500,
    static_retry_max_delay_ms: 5000,
    max_html_response_bytes: 2000000,
    concurrent_requests_per_host: 2,
    delay_between_requests_ms: 0,
    user_agent: "WebsiteScanner/0.1",
    drop_query_parameters: ["utm_*", "gclid", "fbclid", "msclkid"],
    allow_private_networks: false,
    max_redirects: 10
  },
  is_active: true,
  created_at: "2026-07-30T01:00:00Z",
  updated_at: "2026-07-30T01:00:00Z",
  total_scan_count: 1,
  latest_scan_id: 1,
  latest_scan_status: "completed",
  latest_scan_date: "2026-07-30T01:00:00Z",
  latest_scan_discovered_count: 1,
  latest_scan_failed_count: 0
};

const siteDetailFixture = {
  ...siteFixture,
  latest_scan: { ...scanFixture, website_property_id: 3, website_property_name: "Example Site", website_property_base_url: "https://example.com/" },
  recent_scans: [{ ...scanFixture, website_property_id: 3, website_property_name: "Example Site", website_property_base_url: "https://example.com/" }]
};

const sourceFixture = {
  id: 4,
  website_property_id: 3,
  parent_source_id: null,
  root_source_id: null,
  source_type: "sitemap",
  name: "Main sitemap",
  source_url: "https://example.com/sitemap.xml",
  normalized_source_url: "https://example.com/sitemap.xml",
  is_active: true,
  discovery_mode: "configured",
  settings_json: {},
  last_refresh_status: "completed",
  last_refresh_started_at: "2026-07-30T01:00:00Z",
  last_refresh_finished_at: "2026-07-30T01:00:01Z",
  last_successful_refresh_at: "2026-07-30T01:00:01Z",
  last_http_status: 200,
  last_error_type: null,
  last_error_message: null,
  created_at: "2026-07-30T01:00:00Z",
  updated_at: "2026-07-30T01:00:01Z",
  current_entry_count: 2
};

const refreshFixture = {
  id: 5,
  url_source_id: 4,
  status: "completed",
  started_at: "2026-07-30T01:00:00Z",
  finished_at: "2026-07-30T01:00:01Z",
  http_status: 200,
  fetched_url: "https://example.com/sitemap.xml",
  final_url: "https://example.com/sitemap.xml",
  response_bytes: 120,
  content_type: "application/xml",
  discovered_entry_count: 2,
  accepted_entry_count: 2,
  rejected_entry_count: 0,
  child_source_count: 0,
  entries_added: 2,
  entries_updated: 0,
  entries_no_longer_current: 0,
  error_type: null,
  error_message: null,
  warnings_json: []
};

const jobFixture = {
  id: 11,
  job_type: "scan",
  status: "completed",
  presentation_status: "completed",
  priority: 100,
  scan_id: 1,
  source_refresh_id: null,
  website_property_id: null,
  dedupe_key: "scan:1",
  payload_json: { scan_id: 1 },
  progress_version: 1,
  progress_json: {},
  current_operation: null,
  progress_current: null,
  progress_total: null,
  progress_unit: null,
  result_json: null,
  created_at: "2026-07-30T01:00:00Z",
  available_at: "2026-07-30T01:00:00Z",
  claimed_at: null,
  started_at: "2026-07-30T01:00:01Z",
  heartbeat_at: null,
  lease_expires_at: null,
  finished_at: "2026-07-30T01:00:03Z",
  worker_id: null,
  attempt_count: 1,
  max_attempts: 1,
  cancellation_requested_at: null,
  cancelled_at: null,
  error_type: null,
  error_message: null,
  last_error_at: null
};

const workerHealthFixture = {
  online_workers: 1,
  total_concurrency: 1,
  last_worker_heartbeat: "2026-07-30T01:00:00Z",
  queued_work_has_worker: true,
  offline_threshold_seconds: 20
};

const inventoryFixture = {
  normalized_url: "https://example.com/a",
  resource_id: 2,
  source_count: 2,
  source_types: ["manual", "sitemap"],
  sources: [
    { id: 4, name: "Main sitemap", type: "sitemap", entry_id: 6, raw_url: "https://example.com/a" },
    { id: 7, name: "Manual URLs", type: "manual", entry_id: 8, raw_url: "/a" }
  ],
  scope_decision: "crawlable",
  validation_state: "valid",
  sitemap_lastmod: "2026-01-01",
  latest_scan_status: "completed",
  latest_fetch_date: "2026-07-30T01:00:02Z",
  classification: "source_and_crawl",
  suppression_id: null,
  is_suppressed: false,
  suppressed_at: null
};

const persistentPageFixture = {
  site_page_id: 12,
  resource_id: 2,
  normalized_url: "https://example.com/page",
  host: "example.com",
  path: "/page",
  query: "",
  owner_label: "Documentation",
  workflow_status: "needs_review",
  workspace_state: "active" as const,
  suppressed_at: null,
  categories: [],
  category_count: 0,
  note_count: 0,
  associated_at: "2026-07-30T01:00:02Z",
  observation_count: 2,
  first_observed_at: "2026-07-30T01:00:02Z",
  latest_observed_at: "2026-08-05T01:00:02Z",
  latest_snapshot_id: 9,
  latest_scan_id: 1,
  latest_http_status: 200,
  latest_title: "Observed Page",
  latest_retrieval_method: "conditional_not_modified",
  latest_parse_method: "reused_not_modified",
  latest_reused_from_snapshot_id: 8,
  latest_fetch_state: "fetched",
  latest_error_type: null,
  latest_error_message: null
};

const pageObservationFixture = {
  snapshot_id: 9,
  scan_id: 1,
  site_id: 3,
  site_name: "Example Site",
  scan_created_at: "2026-08-05T01:00:00Z",
  scan_status: "completed",
  scan_started_at: "2026-08-05T01:00:00Z",
  scan_finished_at: "2026-08-05T01:00:03Z",
  observed_at: "2026-08-05T01:00:02Z",
  requested_url: "https://example.com/page",
  final_url: "https://example.com/page",
  http_status: 200,
  retrieval_http_status: 304,
  fetch_state: "fetched",
  error_type: null,
  crawl_depth: 0,
  response_time_ms: 30,
  content_type: "text/html",
  raw_html_sha256: "rawhash",
  head_sha256: "headhash",
  page_title: "Observed Page",
  canonical_url: "https://example.com/page",
  retrieval_method: "conditional_not_modified",
  parse_method: "reused_not_modified",
  content_blob_id: 5,
  parse_artifact_id: 6,
  reused_from_snapshot_id: 8,
  network_bytes_transferred: 0,
  parser_version: "html-parser-v1"
};

const seedFixture = {
  id: 9,
  scan_id: 1,
  resource_id: 2,
  normalized_url: "https://example.com/a",
  requested_url: "https://example.com/a",
  depth: 0,
  queue_state: "queued",
  scope_decision: "crawlable",
  exclusion_reason: null,
  created_at: "2026-07-30T01:00:00Z",
  origins: [
    {
      id: 10,
      origin_type: "sitemap",
      url_source_id: 4,
      url_source_entry_id: 6,
      source_refresh_id: 5,
      raw_url: "https://example.com/a",
      metadata_json: {}
    }
  ]
};

