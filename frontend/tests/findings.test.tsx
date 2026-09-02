import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SiteFindingDetailPage, SiteFindingsWorkspace } from "../src/pages/site-workspace/SiteFindingsWorkspace";
import type { Site } from "../src/types/scans";

const api = vi.hoisted(() => ({
  createFindingEvaluation: vi.fn(),
  getFinding: vi.fn(),
  listFindingEvaluations: vi.fn(),
  listFindings: vi.fn(),
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
});

function renderWorkspace(initialEntry = "/") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[initialEntry]}><SiteFindingsWorkspace site={site} /></MemoryRouter></QueryClientProvider>);
}

function renderDetail() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}><MemoryRouter initialEntries={["/sites/3/findings/4"]}><Routes><Route path="/sites/:siteId/findings/:findingId" element={<SiteFindingDetailPage site={site} />} /></Routes></MemoryRouter></QueryClientProvider>);
}
