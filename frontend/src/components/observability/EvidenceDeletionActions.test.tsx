import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as client from "../../api/client";
import {
  AccessibilityObservationDeleteAction,
  AccessibilityRunDeleteAction,
  AccessibilitySiteDeleteAction,
  EvidenceDeletionNotice,
  PerformanceObservationDeleteAction,
  PerformanceRunDeleteAction,
  PerformanceSiteDeleteAction,
} from "./EvidenceDeletionActions";

vi.mock("../../api/client", () => ({
  getPerformanceObservationDeletePreview: vi.fn(), deletePerformanceObservation: vi.fn(),
  getPerformanceRunDeletePreview: vi.fn(), deletePerformanceRun: vi.fn(),
  getPerformanceSiteDeletePreview: vi.fn(), purgePerformanceSite: vi.fn(),
  getAccessibilityObservationDeletePreview: vi.fn(), deleteAccessibilityObservation: vi.fn(),
  getAccessibilityRunDeletePreview: vi.fn(), deleteAccessibilityRun: vi.fn(),
  getAccessibilitySiteDeletePreview: vi.fn(), purgeAccessibilitySite: vi.fn(),
}));

const result = { observations_deleted: 1, runs_deleted: 0, warnings: [] };
const common = { can_delete: true, reason: null, stored_bytes_reclaimable: 512, shared_payload_blobs: 0, payload_stored_bytes: 512 };

function wrapper(children: ReactNode) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return { queryClient, ...render(<QueryClientProvider client={queryClient}>{children}</QueryClientProvider>) };
}

beforeEach(() => vi.clearAllMocks());
afterEach(cleanup);

describe("observability deletion actions", () => {
  it("deletes Performance and Accessibility observations without typed confirmation", async () => {
    vi.mocked(client.getPerformanceObservationDeletePreview).mockResolvedValue({ ...common, observation_id: 1, run_id: 2, provider: "pagespeed", dimension: "mobile", outcome: "ready", observed_at: "2026-01-01", target_kind: "url", requested_target: "https://example.test", payload_present: true, payload_shared: false, payload_reference_count: 1, payload_raw_bytes: 700, raw_bytes_reclaimable: 700 });
    vi.mocked(client.deletePerformanceObservation).mockResolvedValue(result as never);
    const performanceDeleted = vi.fn();
    const view = wrapper(<PerformanceObservationDeleteAction siteId="3" observationId={1} onDeleted={performanceDeleted} />);
    const invalidation = vi.spyOn(view.queryClient, "invalidateQueries");
    fireEvent.click(screen.getByRole("button", { name: "Delete observation" }));
    expect(await screen.findByText("Provider / dimension")).toBeVisible();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Delete permanently" }));
    await waitFor(() => expect(performanceDeleted).toHaveBeenCalled());
    expect(invalidation).toHaveBeenCalled();
    view.unmount();

    vi.mocked(client.getAccessibilityObservationDeletePreview).mockResolvedValue({ ...common, observation_id: 4, run_id: 5, profile: "desktop", outcome: "ready", observed_at: "2026-01-01", requested_url: "https://example.test", violation_rule_count: 1, incomplete_rule_count: 0, rule_rows_deleted: 1, node_rows_deleted: 2, payload_present: true, payload_shared: false, payload_reference_count: 1, payload_raw_bytes: 700, raw_bytes_reclaimable: 700 });
    vi.mocked(client.deleteAccessibilityObservation).mockResolvedValue(result as never);
    wrapper(<AccessibilityObservationDeleteAction siteId="3" observationId={4} onDeleted={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Delete observation" }));
    expect(await screen.findByText("Rule rows")).toBeVisible();
  });

  it.each([
    ["Performance", <PerformanceRunDeleteAction key="p" siteId="3" runId={8} onDeleted={vi.fn()} />, "DELETE PERFORMANCE RUN 8", client.getPerformanceRunDeletePreview, client.deletePerformanceRun, { ...common, run_id: 8, status: "completed", created_at: "2026-01-01", finished_at: "2026-01-01", completed_count: 100, ready_count: 99, unavailable_count: 0, failed_count: 1, retained_observation_count: 99, deleted_observation_count: 1, payload_blobs_referenced: 1, exclusive_payload_blobs: 1, raw_bytes_reclaimable: 1, background_jobs_removed: 1, job_events_removed: 2 }],
    ["Accessibility", <AccessibilityRunDeleteAction key="a" siteId="3" runId={9} onDeleted={vi.fn()} />, "DELETE ACCESSIBILITY RUN 9", client.getAccessibilityRunDeletePreview, client.deleteAccessibilityRun, { ...common, run_id: 9, status: "completed", created_at: "2026-01-01", finished_at: "2026-01-01", completed_count: 100, ready_count: 99, failed_count: 1, retained_observation_count: 99, deleted_observation_count: 1, rule_rows_removed: 2, node_rows_removed: 3, payload_blobs_referenced: 1, exclusive_payload_blobs: 1, raw_bytes_reclaimable: 1, background_jobs_removed: 1, job_events_removed: 2 }],
  ])("requires the exact %s Run phrase", async (_domain, action, phrase, previewMock, deleteMock, preview) => {
    vi.mocked(previewMock as ReturnType<typeof vi.fn>).mockResolvedValue(preview);
    vi.mocked(deleteMock as ReturnType<typeof vi.fn>).mockResolvedValue(result);
    wrapper(action);
    fireEvent.click(screen.getByRole("button", { name: "Delete run" }));
    const input = await screen.findByRole("textbox");
    expect(await screen.findByText("Collection completed")).toBeVisible();
    expect(screen.getByText("Retained observations")).toBeVisible();
    expect(screen.getByText("Already deleted")).toBeVisible();
    const submit = screen.getByRole("button", { name: "Delete permanently" });
    expect(submit).toBeDisabled();
    fireEvent.change(input, { target: { value: phrase } });
    expect(submit).toBeEnabled();
  });

  it.each([
    [<PerformanceSiteDeleteAction key="p" siteId="3" onDeleted={vi.fn()} />, "DELETE PERFORMANCE", client.getPerformanceSiteDeletePreview],
    [<AccessibilitySiteDeleteAction key="a" siteId="3" onDeleted={vi.fn()} />, "DELETE ACCESSIBILITY", client.getAccessibilitySiteDeletePreview],
  ])("requires exact Site purge confirmation", async (action, phrase, previewMock) => {
    vi.mocked(previewMock as ReturnType<typeof vi.fn>).mockResolvedValue({ ...common, site_id: 3, runs: 2, retained_observations: 100, already_deleted_observations: 1, background_jobs_removed: 2, job_events_removed: 4, payload_blobs_referenced: 1, exclusive_payload_blobs: 1, raw_bytes_reclaimable: 1, rule_rows_removed: 0, node_rows_removed: 0 });
    wrapper(action);
    fireEvent.click(screen.getByRole("button", { name: /Delete all/ }));
    expect(await screen.findByText(phrase)).toBeVisible();
  });

  it("shows the backend reason when deletion is blocked", async () => {
    vi.mocked(client.getPerformanceRunDeletePreview).mockResolvedValue({ ...common, can_delete: false, reason: "A Performance job is still running.", run_id: 8 } as never);
    wrapper(<PerformanceRunDeleteAction siteId="3" runId={8} onDeleted={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Delete run" }));
    expect(await screen.findByText(/A Performance job is still running/)).toBeVisible();
    expect(screen.getByRole("button", { name: "Delete permanently" })).toBeDisabled();
  });

  it("renders post-commit file cleanup warnings", () => {
    wrapper(<EvidenceDeletionNotice result={{ ...result, warnings: ["Database evidence was deleted, but a payload file could not be removed."] } as never} />);
    expect(screen.getByRole("status")).toHaveTextContent("payload file could not be removed");
  });
});
