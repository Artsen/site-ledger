import { focusManager, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SiteIntelligenceOverview } from "../src/pages/site-workspace/SiteIntelligenceOverview";
import type { Site } from "../src/types/scans";
import type { SiteIntelligence } from "../src/types/siteIntelligence";

const api = vi.hoisted(() => ({ getSiteIntelligence: vi.fn() }));
const plans = vi.hoisted(() => ({ previewCollectionPlan: vi.fn(), createCollectionPlan: vi.fn() }));
vi.mock("../src/api/siteIntelligence", () => api);
vi.mock("../src/api/collectionPlans", () => plans);

const site = { id: 3, name: "Example", display_timezone: "UTC" } as Site;
const clock = (value: string | null) => ({
  latest_observed_at: value, latest_completed_at: value,
  oldest_current_observation_at: value, newest_current_observation_at: value,
  source_run_id: null, source_scan_id: null, source_comparison_id: null,
  source_status: value ? "completed" : null,
});
const coverage = (observed: number, eligible: number) => ({ observed, eligible, ratio: eligible ? observed / eligible : null });

function intelligence(): SiteIntelligence {
  return {
    site_id: 3,
    page_population: { active_page_total: 10, suppressed_page_total: 2, workspace_page_total: 12, workflow_counts: {} },
    scan: { present: true, id: 7, status: "completed", created_at: "2026-08-24T01:00:00Z", started_at: null, finished_at: "2026-08-24T01:00:00Z", discovered_count: 12, fetched_count: 9, failed_count: 1, skipped_count: 0, stop_reason: "completed", fatal_error_message: null, active_page_observed: coverage(9, 10), active_page_fetched: coverage(8, 10), clock: clock("2026-08-24T01:00:00Z") },
    comparison: { present: false, comparison_id: null, build_id: null, baseline_scan_id: null, target_scan_id: null, comparison_version: null, algorithm_identity: null, page_counts: {}, resource_counts: {}, link_counts: {}, clock: clock(null) },
    structured_content: { extractor_version: "structured-content-v2", extractor_config_version: "canonical-document-v1", markdown_renderer_version: "structured-markdown-v1", active_pages: 10, eligible_retained_html: 8, ready: 5, partial: 1, unavailable: 0, not_prepared: 2, ineligible: 2, coverage: coverage(6, 8), clock: clock("2026-08-24T02:00:00Z") },
    render: { latest_run: { present: true, id: 4, status: "completed", target_count: 2, created_at: "2026-08-25T02:00:00Z", started_at: null, finished_at: "2026-08-25T02:00:00Z" }, retained_coverage: coverage(8, 10), successful: 1, no_content: 1, redirect: 1, http_error: 1, rate_limited: 1, not_attempted_host_throttled: 1, technical_failure: 2, clock: clock("2026-08-25T02:00:00Z") },
    performance: { contexts: [{ provider: "pagespeed", dimension: "mobile", target_kind: "url", provider_adapter_version: "pagespeed-provider-v1", normalization_version: "performance-normalization-v1", ready: 4, unavailable: 1, failed: 0, coverage: coverage(5, 10), clock: clock("2026-08-26T03:00:00Z") }, { provider: "crux", dimension: "PHONE", target_kind: "url", provider_adapter_version: "crux-provider-v1", normalization_version: "performance-normalization-v1", ready: 2, unavailable: 3, failed: 0, coverage: coverage(5, 10), clock: clock("2026-08-26T03:00:00Z") }], latest_run_id: 8, latest_run_status: "completed", clock: clock("2026-08-26T03:00:00Z") },
    accessibility: { coverage: coverage(4, 20), ready_pages: 3, failed_pages: 1, pages_with_violations: 2, violation_rules: 3, affected_nodes: 6, needs_review_rules: 1, clock: clock("2026-08-27T04:00:00Z") },
    sources: { active_source_count: 2, inactive_source_count: 1, current_inventory_count: 11, suppressed_inventory_count: 2, latest_refresh_status: "completed", latest_refresh_finished_at: "2026-08-27T05:00:00Z" },
    findings: { detected: 2, unknown: 1, acknowledged_detected: 1, unresolved_total: 3, latest_evaluation_id: 6, latest_evidence_horizon_at: "2026-08-27T05:00:00Z", latest_evaluation_completed_at: "2026-08-27T05:01:00Z" },
    activity: { active_job_count: 0, queued_count: 0, running_count: 0, jobs: [] },
    collection_coverage: [{ evidence_domain: "accessibility", target_mode: "missing_current", context_identity: "accessibility:test", context: { profile: "desktop" }, active_page_count: 10, active_page_universe_sha256: "a".repeat(64), eligible: 10, covered: 4, in_flight: 1, active_collection: 1, missing: 5, ineligible: 0, batch_size: 250, estimated_batch_count: 1, collectable: true, non_collectable_reason: null }],
  };
}

describe("Site Intelligence overview", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.getSiteIntelligence.mockResolvedValue(intelligence());
    plans.previewCollectionPlan.mockResolvedValue({ ...intelligence().collection_coverage[0], target_total: 5, limit: 20, offset: 0, targets: [{ position: 0, web_resource_id: 42, requested_url: "https://example.test/missing", selection_reason: "missing_current", latest_compatible_observed_at: null, source_snapshot_id: null, content_blob_id: null }] });
    plans.createCollectionPlan.mockResolvedValue({ id: 91 });
  });
  afterEach(() => cleanup());

  it("shows explicit coverage, independent dates, and separate Performance contexts", async () => {
    renderOverview();
    expect(await screen.findByText("10")).toBeInTheDocument();
    expect(screen.getByText("9 of 10")).toBeInTheDocument();
    expect(screen.getByText("pagespeed / mobile", { exact: false })).toBeInTheDocument();
    expect(screen.getByText("crux / PHONE", { exact: false })).toBeInTheDocument();
    expect(screen.getByText(/Latest Run targeted 2 Pages/)).toBeInTheDocument();
    expect(screen.getByText("Accessibility profile coverage")).toBeInTheDocument();
    expect(screen.getByText("4 of 20")).toBeInTheDocument();
    expect(screen.getByText(/current Page\/profile audits across desktop and mobile/)).toBeInTheDocument();
    expect(screen.getByText(/Missing profiles are not counted as zero violations/)).toBeInTheDocument();
    expect(screen.getAllByText(/Observed Aug 24/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Observed Aug 27/).length).toBeGreaterThan(0);
  });

  it("keeps complete Performance context identities visibly distinct", async () => {
    const value = intelligence();
    const original = value.performance.contexts[0];
    value.performance.contexts = [
      original,
      { ...original, provider_adapter_version: "pagespeed-provider-v2", normalization_version: "performance-normalization-v2" },
    ];
    api.getSiteIntelligence.mockResolvedValue(value);
    renderOverview();
    expect(await screen.findByText(/pagespeed-provider-v1/)).toHaveTextContent("performance-normalization-v1");
    expect(screen.getByText(/pagespeed-provider-v2/)).toHaveTextContent("performance-normalization-v2");
    expect(screen.getAllByText("pagespeed / mobile", { exact: false })).toHaveLength(2);
  });

  it("states missing comparison and missing evidence without implying health", async () => {
    const empty = intelligence();
    empty.page_population.active_page_total = 0;
    empty.performance.contexts = [];
    empty.accessibility.coverage = coverage(0, 0);
    api.getSiteIntelligence.mockResolvedValue(empty);
    renderOverview();
    expect(await screen.findByText("No current-compatible Scan Comparison V3 is available.")).toBeInTheDocument();
    expect(screen.getByText("No Performance evidence. Missing measurements do not imply good performance.")).toBeInTheDocument();
    expect(screen.getAllByText("Not applicable").length).toBeGreaterThan(0);
  });

  it("links summaries to existing Site workspaces and keeps configuration accessible", async () => {
    renderOverview();
    expect(await screen.findByRole("link", { name: "Site configuration" })).toHaveAttribute("href", "/sites/3/settings");
    expect(screen.getByRole("link", { name: "URL Inventory" })).toHaveAttribute("href", "/sites/3/inventory");
    expect(screen.getByRole("link", { name: "Scan 7" })).toHaveAttribute("href", "/scans/7");
  });

  it("polls quickly while active and uses bounded idle freshness", async () => {
    vi.useFakeTimers();
    try {
      const active = intelligence();
      active.activity = {
        active_job_count: 1,
        queued_count: 0,
        running_count: 1,
        jobs: [{
          id: 9, job_type: "render_run", status: "running" as const,
          current_operation: "Capturing", progress_current: 1, progress_total: 2,
          progress_unit: "Pages", created_at: "2026-08-27T04:00:00Z",
          started_at: "2026-08-27T04:00:00Z",
        }],
      };
      api.getSiteIntelligence
        .mockResolvedValueOnce(active)
        .mockResolvedValue(intelligence());
      renderOverview();
      await vi.advanceTimersByTimeAsync(0);
      expect(api.getSiteIntelligence).toHaveBeenCalledTimes(1);
      await vi.advanceTimersByTimeAsync(2000);
      expect(api.getSiteIntelligence).toHaveBeenCalledTimes(2);
      await vi.advanceTimersByTimeAsync(5000);
      expect(api.getSiteIntelligence).toHaveBeenCalledTimes(2);
      await vi.advanceTimersByTimeAsync(25_000);
      expect(api.getSiteIntelligence).toHaveBeenCalledTimes(3);
    } finally {
      vi.useRealTimers();
    }
  });

  it("discovers externally started work during bounded idle refresh", async () => {
    vi.useFakeTimers();
    try {
      const active = intelligence();
      active.activity.active_job_count = 1;
      active.activity.running_count = 1;
      api.getSiteIntelligence
        .mockResolvedValueOnce(intelligence())
        .mockResolvedValueOnce(active)
        .mockResolvedValue(intelligence());

      renderOverview();
      await vi.advanceTimersByTimeAsync(0);
      expect(api.getSiteIntelligence).toHaveBeenCalledTimes(1);
      await vi.advanceTimersByTimeAsync(30_000);
      expect(api.getSiteIntelligence).toHaveBeenCalledTimes(2);
      await vi.advanceTimersByTimeAsync(2_000);
      expect(api.getSiteIntelligence).toHaveBeenCalledTimes(3);
    } finally {
      vi.useRealTimers();
    }
  });

  it("refreshes stale Site Intelligence when the window regains focus", async () => {
    renderOverview();
    await waitFor(() => expect(api.getSiteIntelligence).toHaveBeenCalledTimes(1));

    focusManager.setFocused(false);
    focusManager.setFocused(true);

    await waitFor(() => expect(api.getSiteIntelligence).toHaveBeenCalledTimes(2));
    focusManager.setFocused(undefined);
  });

  it("previews missing Pages and confirms visible batch counts before collection", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    const { client } = renderOverview();
    const invalidation = vi.spyOn(client, "invalidateQueries");
    fireEvent.click(await screen.findByRole("button", { name: "View missing" }));
    expect(await screen.findByText("https://example.test/missing")).toBeInTheDocument();
    expect(screen.getByText("42")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Collect missing" }));
    await waitFor(() => expect(plans.createCollectionPlan).toHaveBeenCalledTimes(1));
    expect(invalidation).toHaveBeenCalledWith({ queryKey: ["site-intelligence", "3"] });
    expect(confirm).toHaveBeenCalledWith(expect.stringContaining("Batch 1: 5"));
    confirm.mockRestore();
  });

  it("offers refresh for observation domains and explains retained history", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    plans.previewCollectionPlan.mockImplementation((_siteId, payload) => Promise.resolve({
      ...intelligence().collection_coverage[0],
      target_mode: payload.target_mode,
      target_total: 8,
      missing: 4,
      covered: 6,
      active_collection: 2,
      estimated_batch_count: 1,
      limit: 20,
      offset: 0,
      targets: [],
    }));
    renderOverview();

    fireEvent.click(await screen.findByRole("button", { name: "Refresh current" }));

    await waitFor(() => expect(plans.createCollectionPlan).toHaveBeenCalledWith(3, expect.objectContaining({ target_mode: "refresh_current" })));
    expect(confirm).toHaveBeenCalledWith(expect.stringContaining("Existing observations will be retained"));
    expect(confirm).toHaveBeenCalledWith(expect.stringContaining("2 eligible Pages are already being collected"));
    confirm.mockRestore();
  });

  it("offers refresh for Performance, Accessibility, and Render but not Structured Content", async () => {
    const value = intelligence();
    const base = value.collection_coverage[0];
    value.collection_coverage = [
      { ...base, evidence_domain: "performance", context_identity: "performance:test", context: { provider: "pagespeed", dimension: "mobile" } },
      base,
      { ...base, evidence_domain: "render", context_identity: "render:test", context: {} },
      { ...base, evidence_domain: "structured_content", context_identity: "structured:test", context: {} },
    ];
    api.getSiteIntelligence.mockResolvedValue(value);
    renderOverview();

    expect(await screen.findAllByRole("button", { name: "Refresh current" })).toHaveLength(3);
    expect(screen.getByText(/time-based refresh does not apply/)).toBeInTheDocument();
  });
});

function renderOverview() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return { client, ...render(<QueryClientProvider client={client}><MemoryRouter><SiteIntelligenceOverview site={site} /></MemoryRouter></QueryClientProvider>) };
}
