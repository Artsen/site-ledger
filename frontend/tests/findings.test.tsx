import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SiteFindingDetailPage, SiteFindingsWorkspace } from "../src/pages/site-workspace/SiteFindingsWorkspace";
import type { Site } from "../src/types/scans";

const api = vi.hoisted(() => ({
  createFindingEvaluation: vi.fn(),
  deleteFinding: vi.fn(),
  getFinding: vi.fn(),
  listFindingEvaluations: vi.fn(),
  listFindings: vi.fn(),
  resetSiteFindings: vi.fn(),
  setFindingAcknowledged: vi.fn(),
}));
vi.mock("../src/api/findings", () => api);

const site = { id: 3, name: "Example", display_timezone: "UTC" } as Site;
const evaluation = {
  id: 7, website_property_id: 3, source_scan_id: 9, evaluator_version: "finding-evaluator-v1",
  detector_bundle_identity: "finding-detectors-v1", input_fingerprint_sha256: "a".repeat(64),
  evidence_horizon_at: "2026-08-28T01:00:00Z", active_page_count: 10,
  active_page_universe_sha256: "b".repeat(64), status: "completed", detected_count: 1,
  clear_count: 8, unknown_count: 1, created_finding_count: 1, resolved_finding_count: 0,
  detector_summary_json: {
    page_http_error: { detector_identity: "page-http-error-v1", detected: 1, clear: 8, unknown: 1, reason_counts: { subject_fetch_unusable: 1 } },
  },
  evidence_manifest_json: {},
  reopened_finding_count: 0, assessment_count: 1, evaluation_checksum_sha256: "c".repeat(64),
  created_at: "2026-08-28T02:00:00Z", started_at: "2026-08-28T02:00:00Z",
  finished_at: "2026-08-28T02:00:01Z", failed_at: null, error_type: null,
  error_message: null, background_job_id: 11,
};

describe("Findings workspace", () => {
  afterEach(() => cleanup());
  beforeEach(() => {
    vi.clearAllMocks();
    api.listFindings.mockResolvedValue({ items: [{
      id: 4, web_resource_id: 12, page_url: "https://example.test/missing",
      finding_type: "page_http_error", finding_label: "Page HTTP error", logical_key_version: "page-http-error-key-v1",
      fingerprint_sha256: "d".repeat(64), condition_state: "detected", current_severity: "medium",
      first_detected_at: "2026-08-28T01:00:00Z", last_detected_at: "2026-08-28T01:00:00Z",
      last_evaluated_evidence_at: "2026-08-28T01:00:00Z", resolved_at: null,
      reopened_at: null, acknowledged_at: null, current_assessment_id: 13,
      page_workspace_state: "active", current_evidence_summary: { http_status: 404 },
    }], total: 1, limit: 50, offset: 0 });
    api.listFindingEvaluations.mockResolvedValue({ items: [evaluation], total: 1, limit: 25, offset: 0 });
    api.createFindingEvaluation.mockResolvedValue(evaluation);
    api.deleteFinding.mockResolvedValue(undefined);
    api.resetSiteFindings.mockResolvedValue({
      site_id: 3, deleted_finding_count: 1, deleted_assessment_count: 1,
      deleted_evidence_reference_count: 2, deleted_evaluation_count: 1,
      deleted_job_count: 1, deleted_job_event_count: 2,
    });
  });

  it("shows current lifecycle state and links to durable Finding history", async () => {
    renderWorkspace();
    expect(await screen.findByRole("link", { name: "https://example.test/missing" })).toHaveAttribute("href", "/sites/3/findings/4");
    expect(screen.getAllByText("Detected").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Medium").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Open").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Page HTTP error").length).toBeGreaterThan(0);
  });

  it("sends all URL-backed current-view filters to the API", async () => {
    renderWorkspace("/?type=page_noindex&state=detected&severity=medium&acknowledged=false");
    await waitFor(() => expect(api.listFindings).toHaveBeenCalledWith(
      3,
      expect.stringContaining("finding_type=page_noindex"),
    ));
    const query = api.listFindings.mock.calls.at(-1)?.[1] as string;
    expect(query).toContain("condition_state=detected");
    expect(query).toContain("severity=medium");
    expect(query).toContain("acknowledged=false");
    fireEvent.change(await screen.findByLabelText("Finding type"), { target: { value: "page_indexability_conflict" } });
    await waitFor(() => expect(api.listFindings.mock.calls.at(-1)?.[1]).toContain("finding_type=page_indexability_conflict"));
  });

  it("renders detector-specific canonical evidence instead of raw JSON", async () => {
    api.getFinding.mockResolvedValue({
      ...(await api.listFindings()).items[0],
      finding_type: "page_canonical_target_http_error",
      finding_label: "Canonical target HTTP error",
      logical_key_version: "page-canonical-target-http-error-key-v1",
      website_property_id: 3,
      created_at: "2026-08-28T01:00:00Z",
      updated_at: "2026-08-28T01:00:00Z",
      assessments: [{
        id: 14,
        finding_evaluation_id: 7,
        outcome: "detected",
        severity: "high",
        evidence_observed_at: "2026-08-28T01:00:00Z",
        details_json: { canonical_url: "https://example.test/gone", target_http_status: 404, transition: "detected->detected" },
        assessment_sha256: "e".repeat(64),
        created_at: "2026-08-28T01:00:00Z",
        evaluation,
        evidence_references: [
          { id: 1, position: 0, role: "primary", evidence_kind: "resource_snapshot", evidence_id: 20, evidence_observed_at: "2026-08-28T01:00:00Z", metadata_json: {}, retained: true, href: "/scans/9/pages/20" },
          { id: 2, position: 1, role: "canonical_target", evidence_kind: "resource_snapshot", evidence_id: 21, evidence_observed_at: "2026-08-28T01:00:00Z", metadata_json: {}, retained: true, href: "/scans/9/pages/21" },
        ],
      }],
    });
    renderDetail();
    expect(await screen.findByText("Canonical target HTTP error")).toBeInTheDocument();
    expect(screen.getByText("Canonical -> https://example.test/gone; target HTTP 404")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Canonical Target: Resource Snapshot 21" })).toBeInTheDocument();
  });

  it("queues an evaluation and moves to evaluation provenance", async () => {
    renderWorkspace();
    fireEvent.click(await screen.findByRole("button", { name: /Run evaluation/ }));
    await waitFor(() => expect(api.createFindingEvaluation).toHaveBeenCalledWith(3));
    expect(await screen.findByText("#7")).toBeInTheDocument();
    expect(screen.getByText("1 new, 0 resolved, 0 reopened")).toBeInTheDocument();
    expect(screen.getByText("HTTP errors")).toBeInTheDocument();
    expect(screen.getByText("1 detected · 8 clear · 1 unknown")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Unknown reasons"));
    expect(screen.getByText("Subject Fetch Unusable: 1")).toBeInTheDocument();
  });

  it("keeps V3 and V4 bundle identities visible as separate history", async () => {
    api.listFindingEvaluations.mockResolvedValue({
      items: [
        { ...evaluation, id: 8, detector_bundle_identity: "finding-detectors-v4" },
        { ...evaluation, detector_bundle_identity: "finding-detectors-v3" },
      ],
      total: 2,
      limit: 25,
      offset: 0,
    });
    renderWorkspace("/?view=evaluations");
    expect(await screen.findByText("finding-detectors-v4")).toBeInTheDocument();
    expect(screen.getByText("finding-detectors-v3")).toBeInTheDocument();
  });

  it("summarizes topology Findings and renders bounded target evidence", async () => {
    const broken = {
      ...(await api.listFindings()).items[0],
      finding_type: "page_broken_internal_links",
      finding_label: "Broken internal links",
      logical_key_version: "page-broken-internal-links-key-v1",
      current_severity: "high",
      current_evidence_summary: { broken_target_count: 6, broken_occurrence_count: 14 },
    };
    api.listFindings.mockResolvedValue({ items: [broken], total: 1, limit: 50, offset: 0 });
    const workspace = renderWorkspace();
    expect((await screen.findAllByText("Broken internal links")).length).toBeGreaterThan(1);
    expect(screen.getByText("6 broken targets")).toBeInTheDocument();
    workspace.unmount();

    api.getFinding.mockResolvedValue({
      ...broken,
      website_property_id: 3,
      created_at: "2026-08-28T01:00:00Z",
      updated_at: "2026-08-28T01:00:00Z",
      assessments: [{
        id: 14, finding_evaluation_id: 7, outcome: "detected", severity: "high",
        evidence_observed_at: "2026-08-28T01:00:00Z", assessment_sha256: "e".repeat(64),
        created_at: "2026-08-28T01:00:00Z", evaluation,
        details_json: {
          broken_target_count: 2, broken_occurrence_count: 3, evidence_sample_count: 3,
          evidence_truncated: false, transition: "detected->detected",
          target_samples: [
            { requested_url: "https://example.test/gone", http_status: 404 },
            { requested_url: "https://example.test/server-error", http_status: 500 },
          ],
        },
        evidence_references: [
          { id: 1, position: 0, role: "primary", evidence_kind: "resource_snapshot", evidence_id: 20, evidence_observed_at: "2026-08-28T01:00:00Z", metadata_json: {}, retained: true, href: "/scans/9/pages/20" },
          { id: 2, position: 1, role: "broken_occurrence", evidence_kind: "resource_occurrence", evidence_id: 31, evidence_observed_at: "2026-08-28T01:00:00Z", metadata_json: {}, retained: true, href: "/scans/9/pages/20" },
        ],
      }],
    });
    renderDetail();
    expect(await screen.findByText("3 broken internal link occurrences across 2 target Pages")).toBeInTheDocument();
    expect(screen.getByText("https://example.test/gone -> HTTP 404")).toBeInTheDocument();
    expect(screen.getByText("https://example.test/server-error -> HTTP 500")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Broken Occurrence: Resource Occurrence 31" })).toBeInTheDocument();
  });

  it("presents redirect topology as requested and final URL pairs", async () => {
    const current = (await api.listFindings()).items[0];
    api.getFinding.mockResolvedValue({
      ...current,
      finding_type: "page_internal_links_to_redirects",
      finding_label: "Internal links to redirects",
      logical_key_version: "page-internal-links-to-redirects-key-v1",
      current_evidence_summary: { redirect_target_count: 1, redirect_occurrence_count: 8 },
      website_property_id: 3,
      created_at: "2026-08-28T01:00:00Z",
      updated_at: "2026-08-28T01:00:00Z",
      assessments: [{
        id: 15, finding_evaluation_id: 7, outcome: "detected", severity: "medium",
        evidence_observed_at: "2026-08-28T01:00:00Z", assessment_sha256: "f".repeat(64),
        created_at: "2026-08-28T01:00:00Z", evaluation,
        details_json: {
          redirect_target_count: 1, redirect_occurrence_count: 8, evidence_sample_count: 8,
          evidence_truncated: false, transition: "detected->detected",
          target_samples: [{ requested_url: "https://example.test/old", final_url: "https://example.test/new" }],
        },
        evidence_references: [],
      }],
    });
    renderDetail();
    expect(await screen.findByText("Internal links to redirects")).toBeInTheDocument();
    expect(screen.getByText("8 internal link occurrences point to 1 redirecting Page")).toBeInTheDocument();
    expect(screen.getByText("https://example.test/old -> https://example.test/new")).toBeInTheDocument();
  });

  it("presents sitemap correlation summaries, independent clocks, and manifest selection", async () => {
    const current = {
      ...(await api.listFindings()).items[0],
      finding_type: "sitemap_page_http_error",
      finding_label: "Sitemap Page HTTP error",
      logical_key_version: "sitemap-page-http-error-key-v1",
      current_evidence_summary: { http_status: 404, sitemap_source_count: 2 },
    };
    api.listFindings.mockResolvedValue({ items: [current], total: 1, limit: 50, offset: 0 });
    const workspace = renderWorkspace();
    expect(await screen.findByText("HTTP 404 · declared in 2 sitemap Sources")).toBeInTheDocument();
    workspace.unmount();

    const v5Evaluation = {
      ...evaluation,
      evaluator_version: "finding-evaluator-v3",
      detector_bundle_identity: "finding-detectors-v5",
      evidence_manifest_json: {
        schema: "finding-evidence-manifest-v1",
        static: { scan_id: 9 },
        sitemap_roots: [
          {
            url_source_id: 4,
            refresh_tree: {
              url_source_id: 4, source_refresh_id: 91, sitemap_document_type: "urlset",
              status: "completed", membership_materialized: true, children: [],
            },
          },
          { url_source_id: 7, refresh_tree: null },
        ],
      },
    };
    api.listFindingEvaluations.mockResolvedValue({ items: [v5Evaluation], total: 1, limit: 25, offset: 0 });
    renderWorkspace("/?view=evaluations");
    expect(await screen.findByText("Scan #9 · 2 sitemap roots · 1 usable refreshes")).toBeInTheDocument();
    cleanup();

    api.getFinding.mockResolvedValue({
      ...current,
      website_property_id: 3,
      created_at: "2026-09-03T01:00:00Z",
      updated_at: "2026-09-03T02:00:00Z",
      assessments: [{
        id: 19, finding_evaluation_id: 7, outcome: "detected", severity: "medium",
        evidence_observed_at: "2026-09-03T02:00:00Z", assessment_sha256: "f".repeat(64),
        created_at: "2026-09-03T02:00:00Z", evaluation: v5Evaluation,
        details_json: {
          http_status: 404, sitemap_source_count: 1, membership_sample_count: 1,
          membership_evidence_truncated: false, transition: "detected->detected",
          sitemap_membership_samples: [{
            source_entry_observation_id: 31, url_source_id: 4, source_refresh_id: 91,
            source_refresh_finished_at: "2026-09-03T02:00:00Z",
            raw_url: "https://example.test/missing",
          }],
        },
        evidence_references: [
          { id: 1, position: 0, role: "primary", evidence_kind: "resource_snapshot", evidence_id: 20, evidence_observed_at: "2026-09-03T01:00:00Z", metadata_json: {}, retained: true, href: "/scans/9/pages/20" },
          { id: 2, position: 1, role: "sitemap_membership", evidence_kind: "source_entry_observation", evidence_id: 31, evidence_observed_at: "2026-09-03T02:00:00Z", metadata_json: { source_refresh_id: 91 }, retained: true, href: "/sites/3/sources?source_id=4&refresh_id=91" },
        ],
      }],
    });
    renderDetail();
    expect(await screen.findByText("HTTP 404 · declared in 1 sitemap Source")).toBeInTheDocument();
    expect(screen.getByText(/Source #4 · refresh #91/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Sitemap Membership: Source Entry Observation 31" })).toHaveAttribute("href", "/sites/3/sources?source_id=4&refresh_id=91");
    expect(screen.getByText(/Sep 3, 1:00 AM UTC/)).toBeInTheDocument();
    expect(screen.getAllByText(/Sep 3, 2:00 AM UTC/).length).toBeGreaterThan(0);
  });

  it("requires deliberate confirmation and preserves rebuild access when resetting", async () => {
    renderWorkspace("/?view=evaluations");
    expect(await screen.findByRole("button", { name: "Reset Findings..." })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Run evaluation/ })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Reset Findings..." }));
    expect(screen.getByText(/Collected website evidence is not deleted/)).toBeInTheDocument();
    const remove = screen.getByRole("button", { name: "Delete permanently" });
    expect(remove).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Type RESET to confirm"), { target: { value: "RESET" } });
    expect(remove).toBeEnabled();
    fireEvent.click(remove);
    await waitFor(() => expect(api.resetSiteFindings).toHaveBeenCalledWith(3));
    await waitFor(() => expect(api.listFindings).toHaveBeenCalledTimes(1));
    expect(screen.getByRole("button", { name: /Run evaluation/ })).toBeInTheDocument();
  });

  it("shows an active-evaluation reset conflict without clearing the workspace", async () => {
    api.resetSiteFindings.mockRejectedValue(new Error("Finding deletion is unavailable while a Finding evaluation is queued or running."));
    renderWorkspace();
    fireEvent.click(await screen.findByRole("button", { name: "Reset Findings..." }));
    fireEvent.change(screen.getByLabelText("Type RESET to confirm"), { target: { value: "RESET" } });
    fireEvent.click(screen.getByRole("button", { name: "Delete permanently" }));
    expect(await screen.findByText("Could not complete Finding deletion")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "https://example.test/missing" })).toBeInTheDocument();
  });

  it("deletes one Finding only after confirmation and returns to the list", async () => {
    api.getFinding.mockResolvedValue({
      ...(await api.listFindings()).items[0],
      website_property_id: 3,
      created_at: "2026-08-28T01:00:00Z",
      updated_at: "2026-08-28T01:00:00Z",
      assessments: [],
    });
    renderDetail();
    fireEvent.click(await screen.findByRole("button", { name: "Delete Finding..." }));
    expect(screen.getByText(/completed evaluation that produced this Finding is not reset/)).toBeInTheDocument();
    expect(screen.getByText(/Collected website evidence is preserved/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Delete permanently" }));
    await waitFor(() => expect(api.deleteFinding).toHaveBeenCalledWith(3, "4"));
    expect(await screen.findByText("findings-list-destination")).toBeInTheDocument();
  });
});

function renderWorkspace(initialEntry = "/") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[initialEntry]}><SiteFindingsWorkspace site={site} /></MemoryRouter></QueryClientProvider>);
}

function renderDetail() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}><MemoryRouter initialEntries={["/sites/3/findings/4"]}><Routes><Route path="/sites/:siteId/findings/:findingId" element={<SiteFindingDetailPage site={site} />} /><Route path="/sites/:siteId/findings" element={<p>findings-list-destination</p>} /></Routes></MemoryRouter></QueryClientProvider>);
}
