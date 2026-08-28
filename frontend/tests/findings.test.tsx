import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SiteFindingsWorkspace } from "../src/pages/site-workspace/SiteFindingsWorkspace";
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
      finding_type: "page_http_error", logical_key_version: "page-http-error-key-v1",
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
    expect(screen.getByText("Medium")).toBeInTheDocument();
    expect(screen.getByText("Open")).toBeInTheDocument();
  });

  it("queues an evaluation and moves to evaluation provenance", async () => {
    renderWorkspace();
    fireEvent.click(await screen.findByRole("button", { name: /Run evaluation/ }));
    await waitFor(() => expect(api.createFindingEvaluation).toHaveBeenCalledWith(3));
    expect(await screen.findByText("#7")).toBeInTheDocument();
    expect(screen.getByText("1 new, 0 resolved, 0 reopened")).toBeInTheDocument();
  });
});

function renderWorkspace() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}><MemoryRouter><SiteFindingsWorkspace site={site} /></MemoryRouter></QueryClientProvider>);
}
