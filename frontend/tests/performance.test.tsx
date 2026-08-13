import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Outlet, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { PerformanceEvidencePage, SitePerformancePage } from "../src/pages/PerformanceWorkspace";
import type { Site } from "../src/types/scans";

const api = vi.hoisted(() => ({
  getPerformanceProviders: vi.fn(),
  getLatestPerformance: vi.fn(),
  listPerformanceRuns: vi.fn(),
  listSitePages: vi.fn(),
  createPerformanceRun: vi.fn(),
  getPerformanceObservation: vi.fn(),
  getPerformancePayload: vi.fn(),
  getPageLatestPerformance: vi.fn(),
}));

vi.mock("../src/api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../src/api/client")>()),
  ...api,
}));

const site = { id: 3, name: "Example", display_timezone: "UTC" } as Site;
const capabilities = {
  pagespeed: { configured: true, adapter_version: "pagespeed-provider-v1" },
  crux: { configured: true, adapter_version: "crux-provider-v1" },
  normalization_version: "performance-normalization-v1",
  default_page_limit: 10,
  hard_page_limit: 25,
};

describe("Performance workspace", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.getPerformanceProviders.mockResolvedValue(capabilities);
    api.getLatestPerformance.mockResolvedValue({ items: [], total: 0, limit: 500, offset: 0 });
    api.listPerformanceRuns.mockResolvedValue({ items: [], total: 0, limit: 25, offset: 0 });
    api.listSitePages.mockResolvedValue({ items: [page(8), page(9)], total: 2, limit: 10, offset: 0 });
    api.createPerformanceRun.mockResolvedValue({ id: 41 });
    api.getPageLatestPerformance.mockResolvedValue({ items: [], total: 0, limit: 10, offset: 0 });
  });

  afterEach(() => cleanup());

  it("shows a clear provider setup state without attempting collection", async () => {
    api.getPerformanceProviders.mockResolvedValue({ ...capabilities, pagespeed: { ...capabilities.pagespeed, configured: false }, crux: { ...capabilities.crux, configured: false } });
    renderWorkspace(<SitePerformancePage />);
    expect(await screen.findByText("Google providers are not configured.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Collect Performance" })).toBeDisabled();
    expect(api.createPerformanceRun).not.toHaveBeenCalled();
  });

  it("separates Overview, Lab, Field, and Runs views", async () => {
    renderWorkspace(<SitePerformancePage />);
    expect(await screen.findByRole("tab", { name: "Overview" })).toHaveAttribute("aria-selected", "true");
    fireEvent.click(screen.getByRole("tab", { name: "Lab" }));
    expect(screen.getByRole("tab", { name: "Lab" })).toHaveAttribute("aria-selected", "true");
    fireEvent.click(screen.getByRole("tab", { name: /Runs/ }));
    expect(screen.getByText("No Performance runs")).toBeInTheDocument();
  });

  it("calculates provider requests and creates one bounded run", async () => {
    renderWorkspace(<SitePerformancePage />);
    fireEvent.click(await screen.findByRole("button", { name: "Collect Performance" }));
    fireEvent.click(await screen.findByRole("checkbox", { name: /Page 8/ }));
    fireEvent.click(await screen.findByRole("checkbox", { name: /Page 9/ }));
    expect(screen.getByText(/This will make/)).toHaveTextContent("10 provider requests");
    fireEvent.click(screen.getByRole("button", { name: "Start collection" }));
    await waitFor(() => expect(api.createPerformanceRun).toHaveBeenCalledWith("3", expect.objectContaining({ resource_ids: [8, 9], include_origin_crux: true })));
  });

  it("manages collection dialog focus and closes with Escape", async () => {
    renderWorkspace(<SitePerformancePage />);
    const trigger = await screen.findByRole("button", { name: "Collect Performance" });
    trigger.focus();
    fireEvent.click(trigger);
    const dialog = screen.getByRole("dialog", { name: "Collect Performance" });
    await waitFor(() => expect(dialog).toContainElement(document.activeElement as HTMLElement));
    fireEvent.keyDown(dialog, { key: "Escape" });
    expect(screen.queryByRole("dialog", { name: "Collect Performance" })).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });

  it("treats unavailable CrUX evidence as normal field availability", async () => {
    api.getLatestPerformance.mockResolvedValue({ items: [observation({ outcome: "unavailable", error_type: "no_field_data", error_message: "No qualifying dataset." })], total: 1, limit: 500, offset: 0 });
    renderWorkspace(<SitePerformancePage />);
    fireEvent.click(await screen.findByRole("tab", { name: "Field" }));
    expect(screen.getByText("No field data available")).toBeInTheDocument();
    expect(screen.getByText("No qualifying dataset.")).toBeInTheDocument();
  });

  it("renders raw provider text escaped and exposes provenance", async () => {
    api.getPerformanceObservation.mockResolvedValue(observation({ payload_sha256: "a".repeat(64) }));
    api.getPerformancePayload.mockResolvedValue('<img src=x onerror="alert(1)">{"safe":true}');
    renderWorkspace(<PerformanceEvidencePage />, "/sites/3/performance/evidence/12", "performance/evidence/:observationId");
    expect(await screen.findByText(/<img src=x/)).toBeInTheDocument();
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
    expect(screen.getByText("pagespeed-provider-v1")).toBeInTheDocument();
    expect(screen.getByText("performance-normalization-v1")).toBeInTheDocument();
  });
});

function renderWorkspace(node: React.ReactNode, initial = "/sites/3/performance", childPath = "performance") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[initial]}><Routes><Route path="sites/:siteId" element={<Outlet context={{ site }} />}><Route path={childPath} element={node} /><Route path="performance/runs/:runId" element={<div>Run created</div>} /></Route></Routes></MemoryRouter></QueryClientProvider>);
}

function page(id: number) {
  return { resource_id: id, latest_title: `Page ${id}`, normalized_url: `https://example.com/${id}` };
}

function observation(overrides: Record<string, unknown> = {}) {
  return {
    id: 12, performance_run_id: 4, website_property_id: 3, web_resource_id: 8,
    provider: "crux", provider_adapter_version: "pagespeed-provider-v1", normalization_version: "performance-normalization-v1",
    target_kind: "url", requested_target: "https://example.com/8", provider_target: "https://example.com/8", dimension: "PHONE", outcome: "ready",
    metrics_json: { lcp: { value: 2200, unit: "ms" } }, normalized_sha256: "b".repeat(64), provider_analysis_at: null,
    provider_period_json: null, provider_product_version: null, observed_at: "2026-08-12T12:00:00Z", error_type: null, error_message: null,
    page_url: "https://example.com/8", payload_sha256: "a".repeat(64), payload_raw_byte_size: 40, payload_stored_byte_size: 35,
    ...overrides,
  };
}
