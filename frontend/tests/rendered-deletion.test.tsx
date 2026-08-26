import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as client from "../src/api/client";
import { RenderRunTargetTable } from "../src/components/rendered/RenderRunTargetTable";
import { RenderRunDeleteAction, RenderTargetBulkDeleteAction } from "../src/components/rendered/RenderedEvidenceDeletionActions";

vi.mock("../src/api/client", () => ({
  listRenderRunTargets: vi.fn(),
  getRenderTargetDeletionPreview: vi.fn(),
  deleteRenderTargetEvidence: vi.fn(),
  getRenderRunDeletionPreview: vi.fn(),
  deleteRenderRun: vi.fn(),
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

beforeEach(() => vi.clearAllMocks());
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
    expect(screen.getAllByText("No retained evidence")).toHaveLength(2);
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
});

function target(id: number, requestedUrl: string, presentationState: "evidence_deleted" | "not_attempted", deletedAt: string | null) {
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
    has_browser_evidence: false,
    finished_at: null,
    presentation_state: presentationState,
  };
}

function wrapper(children: React.ReactNode) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={queryClient}><MemoryRouter>{children}</MemoryRouter></QueryClientProvider>);
}
