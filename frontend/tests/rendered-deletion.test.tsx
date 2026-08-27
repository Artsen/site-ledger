import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Outlet, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as client from "../src/api/client";
import { RenderRunTargetTable } from "../src/components/rendered/RenderRunTargetTable";
import { RenderedDeletionNotice, RenderRunDeleteAction, RenderTargetBulkDeleteAction } from "../src/components/rendered/RenderedEvidenceDeletionActions";
import { RenderedEvidencePage, RenderRunPage, SiteRenderedPage } from "../src/pages/RenderedWorkspace";
import type { RenderRunTarget, Site } from "../src/types/scans";

vi.mock("../src/api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../src/api/client")>()),
  listRenderRunTargets: vi.fn(),
  getRenderTargetDeletionPreview: vi.fn(),
  deleteRenderTargetEvidence: vi.fn(),
  getRenderRunDeletionPreview: vi.fn(),
  deleteRenderRun: vi.fn(),
  getRenderedObservationDeletionPreview: vi.fn(),
  deleteRenderedObservation: vi.fn(),
  getSiteRenderedObservation: vi.fn(),
  getRenderRun: vi.fn(),
  listRenderRuns: vi.fn(),
  cancelRenderRun: vi.fn(),
  rerenderTargets: vi.fn(),
}));

const impact = {
  can_delete: true,
  reason: null,
  targets_requested: 2,
  observations: 1,
  targets_already_without_evidence: 1,
  runs: 1,
  run_targets: 2,
  deleted_targets: 1,
  unattempted_targets: 1,
  legacy_observations: 0,
  network_rows: 3,
  console_rows: 2,
  page_error_rows: 1,
  artifact_rows: 2,
  artifact_blobs_referenced: 2,
  exclusive_artifact_blobs: 1,
  shared_artifact_blobs_retained: 1,
  raw_bytes_reclaimable: 2_048,
  stored_bytes_reclaimable: 1_024,
  background_jobs: 1,
  job_events: 2,
  child_rerender_links_detached: 1,
};

const result = {
  observations_deleted: 1,
  runs_deleted: 0,
  warnings: [],
};

const warning = "Could not delete rendered artifact file screenshot.png: access denied";
const site = { id: 3, name: "Example", display_timezone: "UTC" } as Site;
const runFixture = {
  id: 8,
  status: "completed",
  presentation_status: "completed",
  trigger: "site_workspace",
  source_scan_id: null,
  target_count: 1,
  attempted_count: 1,
  completed_count: 1,
  failed_count: 0,
  skipped_count: 0,
  artifact_count: 0,
  retained_observation_count: 1,
  deleted_observation_count: 0,
  unattempted_target_count: 0,
  retained_artifact_count: 0,
  configuration_json: {},
  summary: { successful_renders: 1, no_content_responses: 0, redirect_responses: 0, http_error_responses: 0, rate_limited: 0, skipped_after_throttling: 0, technical_failures: 0, artifacts_retained: 0 },
  created_at: "2026-08-26T10:00:00Z",
  started_at: "2026-08-26T10:00:01Z",
  finished_at: "2026-08-26T10:00:02Z",
};
const observationFixture = {
  id: 41,
  render_run_id: 8,
  render_run_target_id: 1,
  snapshot_id: null,
  web_resource_id: 11,
  capture_state: "completed",
  requested_url: "https://example.com/page",
  final_url: "https://example.com/page",
  navigation_http_status: 200,
  warnings_json: [],
  artifacts: [],
};

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(client.listRenderRunTargets).mockResolvedValue({ items: [], total: 0, limit: 50, offset: 0 });
  vi.mocked(client.getRenderRun).mockResolvedValue(runFixture as never);
  vi.mocked(client.listRenderRuns).mockResolvedValue({ items: [], total: 0, limit: 25, offset: 0 });
  vi.mocked(client.getSiteRenderedObservation).mockResolvedValue(observationFixture as never);
  vi.mocked(client.getRenderedObservationDeletionPreview).mockResolvedValue(impact);
  vi.mocked(client.getRenderRunDeletionPreview).mockResolvedValue(impact);
});
afterEach(cleanup);

describe("rendered evidence deletion", () => {
  it("keeps Evidence deleted distinct from Not attempted in the target table", async () => {
    vi.mocked(client.listRenderRunTargets).mockResolvedValue({
      total: 2,
      limit: 50,
      offset: 0,
      items: [
        target(1, "https://example.com/deleted", "evidence_deleted", "2026-08-26T12:00:00Z"),
        target(2, "https://example.com/unattempted", "not_attempted", null),
      ],
    });
    const selected: number[] = [];
    const onSelectedChange = vi.fn((ids: number[]) => selected.splice(0, selected.length, ...ids));
    wrapper(<RenderRunTargetTable siteId="3" runId="8" selected={selected} onSelectedChange={onSelectedChange} />);

    const deletedCheckbox = await screen.findByRole("checkbox", { name: "Select https://example.com/deleted" });
    expect(screen.getByText("Evidence deleted", { selector: "span" })).toBeVisible();
    expect(screen.getByText("Not attempted", { selector: "span" })).toBeVisible();
    expect(screen.getByText("Observation deleted")).toBeVisible();
    expect(screen.getByText("No observation")).toBeVisible();
    fireEvent.click(deletedCheckbox);
    expect(onSelectedChange).toHaveBeenCalledWith([1]);
  });

  it("previews and deletes only retained evidence for selected targets", async () => {
    vi.mocked(client.getRenderTargetDeletionPreview).mockResolvedValue(impact);
    vi.mocked(client.deleteRenderTargetEvidence).mockResolvedValue(result as never);
    const onDeleted = vi.fn();
    wrapper(<RenderTargetBulkDeleteAction siteId="3" runId="8" targetIds={[1, 2]} onDeleted={onDeleted} />);

    fireEvent.click(screen.getByRole("button", { name: "Delete evidence (2)" }));
    expect(await screen.findByText("Targets without evidence")).toBeVisible();
    expect(screen.getByText("Shared artifacts retained")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Delete permanently" }));
    await waitFor(() => expect(client.deleteRenderTargetEvidence).toHaveBeenCalledWith("3", "8", [1, 2]));
    expect(onDeleted).toHaveBeenCalled();
  });

  it("invalidates Scan Page results after rendered evidence deletion", async () => {
    vi.mocked(client.getRenderTargetDeletionPreview).mockResolvedValue(impact);
    vi.mocked(client.deleteRenderTargetEvidence).mockResolvedValue(result as never);
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
    queryClient.setQueryData(["pages", "12", 9, "?limit=50"], { items: [] });
    queryClient.setQueryData(["site-pages", "3", "?limit=50"], { items: [] });
    const scanPages = queryClient.getQueryCache().find({ queryKey: ["pages", "12", 9, "?limit=50"] });
    const sitePages = queryClient.getQueryCache().find({ queryKey: ["site-pages", "3", "?limit=50"] });

    render(<QueryClientProvider client={queryClient}><MemoryRouter><RenderTargetBulkDeleteAction siteId="3" runId="8" targetIds={[1]} onDeleted={vi.fn()} /></MemoryRouter></QueryClientProvider>);
    fireEvent.click(screen.getByRole("button", { name: "Delete evidence (1)" }));
    const submit = await screen.findByRole("button", { name: "Delete permanently" });
    await waitFor(() => expect(submit).toBeEnabled());
    fireEvent.click(submit);

    await waitFor(() => expect(scanPages?.state.isInvalidated).toBe(true));
    expect(sitePages?.state.isInvalidated).toBe(false);
  });

  it("keeps HTTP-error observations inspectable without claiming Page artifacts", async () => {
    vi.mocked(client.listRenderRunTargets).mockResolvedValue({
      total: 5,
      limit: 50,
      offset: 0,
      items: [
        target(1, "https://example.com/rate-limited", "rate_limited", null, { observation_id: 101, navigation_http_status: 429 }),
        target(2, "https://example.com/not-found", "http_error", null, { observation_id: 102, navigation_http_status: 404 }),
        target(3, "https://example.com/success", "successful", null, { observation_id: 103, navigation_http_status: 200, has_page_artifacts: true }),
        target(4, "https://example.com/deleted", "evidence_deleted", "2026-08-26T12:00:00Z"),
        target(5, "https://example.com/unattempted", "not_attempted", null),
      ],
    });
    wrapper(<RenderRunTargetTable siteId="3" runId="8" selected={[]} onSelectedChange={vi.fn()} />);

    expect(await screen.findAllByRole("link", { name: "Inspect evidence" })).toHaveLength(3);
    expect(screen.getAllByText("No Page artifacts")).toHaveLength(2);
    expect(screen.getByText("Page artifacts retained")).toBeVisible();
    expect(screen.getByText("Rate limited", { selector: "span" })).toBeVisible();
    expect(screen.getByText("HTTP error", { selector: "span" })).toBeVisible();
    for (const url of ["https://example.com/deleted", "https://example.com/unattempted"]) {
      const row = screen.getByText(url).closest("tr");
      expect(row).not.toBeNull();
      expect(within(row as HTMLElement).queryByRole("link", { name: "Inspect evidence" })).not.toBeInTheDocument();
    }
  });

  it("requires the exact Render Run confirmation phrase", async () => {
    vi.mocked(client.getRenderRunDeletionPreview).mockResolvedValue(impact);
    wrapper(<RenderRunDeleteAction siteId="3" runId={8} onDeleted={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: "Delete run" }));
    const input = await screen.findByRole("textbox");
    const submit = screen.getByRole("button", { name: "Delete permanently" });
    expect(submit).toBeDisabled();
    fireEvent.change(input, { target: { value: "DELETE RENDER RUN 8" } });
    expect(submit).toBeEnabled();
  });

  it("does not offer target evidence deletion while a Run is active", async () => {
    vi.mocked(client.getRenderRun).mockResolvedValue({ ...runFixture, status: "running", presentation_status: "running", finished_at: null } as never);
    vi.mocked(client.listRenderRunTargets).mockResolvedValue({
      total: 1,
      limit: 50,
      offset: 0,
      items: [target(1, "https://example.com/page", "not_attempted", null)],
    });
    renderWorkspace("/sites/3/rendered/runs/8");

    fireEvent.click(await screen.findByRole("checkbox", { name: "Select https://example.com/page" }));
    expect(screen.getByRole("button", { name: "Rerender 1" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Cancel run" })).toBeVisible();
    expect(screen.queryByRole("button", { name: "Delete evidence (1)" })).not.toBeInTheDocument();
  });

  it("carries a single-observation cleanup warning back to the Run", async () => {
    vi.mocked(client.deleteRenderedObservation).mockResolvedValue({ ...result, warnings: [warning] } as never);
    renderWorkspace("/sites/3/rendered/observations/41");

    fireEvent.click(await screen.findByRole("button", { name: "Delete observation" }));
    const dialog = await screen.findByRole("dialog");
    const submit = within(dialog).getByRole("button", { name: "Delete permanently" });
    await waitFor(() => expect(submit).toBeEnabled());
    fireEvent.click(submit);

    expect(await screen.findByText(warning)).toBeVisible();
    expect(screen.getByText("Cleanup warning:")).toBeVisible();
    expect(screen.getByRole("heading", { name: "Run 8" })).toBeVisible();
  });

  it("carries a whole-Run cleanup warning to the Site Rendered page", async () => {
    vi.mocked(client.deleteRenderRun).mockResolvedValue({ ...result, observations_deleted: 0, runs_deleted: 1, warnings: [warning] } as never);
    renderWorkspace("/sites/3/rendered/runs/8");

    fireEvent.click(await screen.findByRole("button", { name: "Delete run" }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.change(within(dialog).getByRole("textbox"), { target: { value: "DELETE RENDER RUN 8" } });
    const submit = within(dialog).getByRole("button", { name: "Delete permanently" });
    await waitFor(() => expect(submit).toBeEnabled());
    fireEvent.click(submit);

    expect(await screen.findByText(warning)).toBeVisible();
    expect(screen.getByRole("heading", { name: "Rendered" })).toBeVisible();
    expect(screen.getByText("1 Run removed.")).toBeVisible();
  });

  it("renders a normal successful deletion notice without a cleanup warning", () => {
    wrapper(<RenderedDeletionNotice result={result as never} />);
    expect(screen.getByText("Rendered evidence deleted.")).toBeVisible();
    expect(screen.getByText("1 observation removed.")).toBeVisible();
    expect(screen.queryByText("Cleanup warning:")).not.toBeInTheDocument();
  });
});

function target(id: number, requestedUrl: string, presentationState: RenderRunTarget["presentation_state"], deletedAt: string | null, overrides: Partial<RenderRunTarget> = {}): RenderRunTarget {
  return {
    target_id: id,
    position: id,
    web_resource_id: id + 10,
    requested_url: requestedUrl,
    source_snapshot_id: null,
    created_at: "2026-08-26T10:00:00Z",
    evidence_deleted_at: deletedAt,
    observation_id: null,
    capture_state: null,
    navigation_http_status: null,
    duration_ms: null,
    warning_count: null,
    page_error_count: null,
    has_page_artifacts: false,
    finished_at: null,
    presentation_state: presentationState,
    ...overrides,
  };
}

function wrapper(children: React.ReactNode) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={queryClient}><MemoryRouter>{children}</MemoryRouter></QueryClientProvider>);
}

function renderWorkspace(initialEntry: string) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={[initialEntry]}><Routes><Route path="sites/:siteId" element={<Outlet context={{ site }} />}><Route path="rendered" element={<SiteRenderedPage />} /><Route path="rendered/runs/:runId" element={<RenderRunPage />} /><Route path="rendered/observations/:observationId" element={<RenderedEvidencePage />} /></Route></Routes></MemoryRouter></QueryClientProvider>);
}
