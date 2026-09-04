import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { CollectionPlansWorkspace } from "../src/pages/site-workspace/CollectionPlansWorkspace";
import type { Site } from "../src/types/scans";

const api = vi.hoisted(() => ({
  listCollectionPlans: vi.fn(),
  getCollectionPlan: vi.fn(),
  listCollectionPlanTargets: vi.fn(),
  cancelCollectionPlan: vi.fn(),
}));
vi.mock("../src/api/collectionPlans", () => api);

const site = { id: 3, name: "Example", display_timezone: "UTC" } as Site;
const plan = {
  id: 12,
  website_property_id: 3,
  planner_version: "collection-planner-v1",
  evidence_domain: "accessibility",
  target_mode: "missing_current",
  context_identity: "accessibility:test",
  context: { profile: "desktop" },
  active_page_count: 5,
  eligible_count: 5,
  covered_count_at_creation: 2,
  in_flight_count_at_creation: 1,
  active_collection_count_at_creation: null,
  missing_count_at_creation: 3,
  selection_reason_counts: { missing_current: 2 },
  ineligible_count_at_creation: 0,
  target_count: 501,
  batch_size: 250,
  batch_count: 3,
  target_selection_sha256: "a".repeat(64),
  cancellation_requested_at: null,
  created_at: "2026-08-31T12:00:00Z",
  status: "running",
  progress: { batch_count: 3, queued_batches: 1, running_batches: 1, completed_batches: 1, failed_batches: 0, cancelled_batches: 0, target_count: 501, processed_target_count: 325 },
  batches: [
    { id: 1, position: 0, target_start_position: 0, target_count: 250, child_kind: "accessibility", status: "completed", processed_target_count: 250, background_job_id: 10, performance_run_id: null, accessibility_run_id: 20, render_run_id: null, created_at: "2026-08-31T12:00:00Z" },
    { id: 2, position: 1, target_start_position: 250, target_count: 250, child_kind: "accessibility", status: "running", processed_target_count: 75, background_job_id: 11, performance_run_id: null, accessibility_run_id: 21, render_run_id: null, created_at: "2026-08-31T12:00:00Z" },
    { id: 3, position: 2, target_start_position: 500, target_count: 1, child_kind: "accessibility", status: "queued", processed_target_count: 0, background_job_id: 12, performance_run_id: null, accessibility_run_id: 22, render_run_id: null, created_at: "2026-08-31T12:00:00Z" },
  ],
} as const;

describe("Collection Plans workspace", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.listCollectionPlans.mockResolvedValue({ items: [plan], total: 1, limit: 100, offset: 0 });
    api.getCollectionPlan.mockResolvedValue(plan);
    api.listCollectionPlanTargets.mockResolvedValue({
      items: [{
        id: 1,
        position: 0,
        web_resource_id: 42,
        requested_url: "https://example.test/page",
        selection_reason: "missing_current",
        latest_compatible_observed_at: null,
        target_context: { profile: "desktop" },
        source_snapshot_id: null,
        content_blob_id: null,
        created_at: "2026-08-31T12:00:00Z",
      }],
      total: 1,
      limit: 100,
      offset: 0,
    });
    api.cancelCollectionPlan.mockResolvedValue({ ...plan, status: "cancelling", cancellation_requested_at: "2026-08-31T12:01:00Z" });
  });
  afterEach(() => cleanup());

  it("renders frozen target and progress provenance", async () => {
    renderWorkspace("/sites/3/collection-plans/12");
    expect(await screen.findByRole("heading", { name: "Plan 12" })).toBeInTheDocument();
    expect(screen.getByText("325 of 501 Pages processed")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Run 20/ })).toHaveAttribute("href", "/sites/3/accessibility/runs/20");
    expect(screen.getByText("collection-planner-v1")).toBeInTheDocument();
    expect(screen.getAllByText("Missing current").length).toBeGreaterThan(0);
    expect(screen.getByText("https://example.test/page")).toBeInTheDocument();
    expect(screen.getByText("Covered at creation").nextSibling).toHaveTextContent("2");
    expect(screen.getByText("Missing at creation").nextSibling).toHaveTextContent("3");
    expect(screen.getByText("Missing and in flight").nextSibling).toHaveTextContent("1");
    expect(screen.getByText("Total active collection").nextSibling).toHaveTextContent(
      "Not recorded in V1",
    );
  });

  it("shows target mode in Plan history", async () => {
    renderWorkspace("/sites/3/collection-plans");
    expect(await screen.findByRole("link", { name: "Plan 12" })).toBeInTheDocument();
    expect(screen.getByText("Missing current")).toBeInTheDocument();
  });

  it("cancels remaining work through the Plan API", async () => {
    renderWorkspace("/sites/3/collection-plans/12");
    fireEvent.click(await screen.findByRole("button", { name: /Cancel remaining work/ }));
    await waitFor(() => expect(api.cancelCollectionPlan).toHaveBeenCalledWith(3, "12"));
  });
});

function renderWorkspace(initialEntry: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[initialEntry]}>
        <Routes>
          <Route path="/sites/:siteId/collection-plans" element={<CollectionPlansWorkspace site={site} />} />
          <Route path="/sites/:siteId/collection-plans/:planId" element={<CollectionPlansWorkspace site={site} />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}
