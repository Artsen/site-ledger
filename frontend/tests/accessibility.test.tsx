import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Outlet, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  AccessibilityEvidencePage,
  PageAccessibilityPanel,
  SiteAccessibilityPage,
} from "../src/pages/AccessibilityWorkspace";
import type { Site } from "../src/types/scans";

const api = vi.hoisted(() => ({
  getAccessibilityCapabilities: vi.fn(),
  getAccessibilitySummary: vi.fn(),
  listAccessibilityRuns: vi.fn(),
  getAccessibilityPages: vi.fn(),
  getAccessibilityRules: vi.fn(),
  listSitePages: vi.fn(),
  createAccessibilityRun: vi.fn(),
  getAccessibilityObservation: vi.fn(),
  getAccessibilityPayload: vi.fn(),
  getPageAccessibility: vi.fn(),
  getPageLatestAccessibility: vi.fn(),
}));

vi.mock("../src/api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../src/api/client")>()),
  ...api,
}));

const site = { id: 3, name: "Example", display_timezone: "UTC" } as Site;
const capabilities = {
  axe_core_version: "4.12.1",
  detector_bundle_sha256: "a".repeat(64),
  integration_version: "accessibility-engine-v1",
  normalization_version: "accessibility-normalization-v1",
  ruleset_profile: "wcag22-aa-v1",
  ruleset_rule_count: 62,
  ruleset_sha256: "b".repeat(64),
  default_page_limit: 10,
  hard_page_limit: 25,
  profiles: {},
};

describe("Accessibility workspace", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.getAccessibilityCapabilities.mockResolvedValue(capabilities);
    api.getAccessibilitySummary.mockResolvedValue({
      pages_audited: 2,
      profiles_audited: 2,
      pages_with_violations: 1,
      violation_rules: 3,
      affected_nodes: 5,
      needs_review_rules: 2,
      impact_counts: { critical: 1, serious: 2 },
      failed_latest: 1,
      latest_observed_at: "2026-08-13T12:00:00Z",
    });
    api.listAccessibilityRuns.mockResolvedValue({ items: [], total: 0, limit: 25, offset: 0 });
    api.getAccessibilityPages.mockResolvedValue({ items: [], total: 0, limit: 100, offset: 0 });
    api.getAccessibilityRules.mockResolvedValue({ items: [], total: 0, limit: 50, offset: 0 });
    api.listSitePages.mockResolvedValue({ items: [page(8), page(9)], total: 2, limit: 10, offset: 0 });
    api.createAccessibilityRun.mockResolvedValue({ id: 41 });
    api.getPageAccessibility.mockResolvedValue({ items: [], total: 0, limit: 25, offset: 0 });
    api.getPageLatestAccessibility.mockResolvedValue({ items: [], total: 0, limit: 2, offset: 0 });
  });

  afterEach(() => cleanup());

  it("shows current summary and the automated-testing limitation", async () => {
    renderWorkspace(<SiteAccessibilityPage />);
    expect(await screen.findByText("Automated checks are limited.")).toBeInTheDocument();
    expect(screen.getByText("Pages with violations").parentElement).toHaveTextContent("1");
    expect(screen.getByText("Affected elements").parentElement).toHaveTextContent("5");
    expect(screen.queryByText(/compliant/i)).not.toBeInTheDocument();
  });

  it("separates Overview, Pages, Rules, and Runs with empty states", async () => {
    renderWorkspace(<SiteAccessibilityPage />);
    expect(await screen.findByRole("tab", { name: "Overview" })).toHaveAttribute("aria-selected", "true");
    fireEvent.click(screen.getByRole("tab", { name: "Pages" }));
    expect(await screen.findByText("No audited Pages match")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "Rules" }));
    expect(await screen.findByText("No current rule evidence")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: /Runs/ }));
    expect(screen.getByText("No Accessibility runs")).toBeInTheDocument();
  });

  it("calculates dual-profile and Desktop-only audit counts", async () => {
    renderWorkspace(<SiteAccessibilityPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Run Accessibility Audit" }));
    fireEvent.click(await screen.findByRole("checkbox", { name: /Page 8/ }));
    fireEvent.click(await screen.findByRole("checkbox", { name: /Page 9/ }));
    expect(screen.getByText(/Pages ×/)).toHaveTextContent("2 Pages × 2 profiles = 4 browser audits");
    fireEvent.click(screen.getByRole("checkbox", { name: /Mobile/ }));
    expect(screen.getByText(/Pages ×/)).toHaveTextContent("2 Pages × 1 profiles = 2 browser audits");
    fireEvent.click(screen.getByRole("button", { name: "Start 2 audits" }));
    await waitFor(() => expect(api.createAccessibilityRun).toHaveBeenCalledWith("3", {
      resource_ids: [8, 9],
      profiles: ["desktop"],
      trigger: "site_workspace",
    }));
  });

  it("traps dialog focus, closes with Escape, and restores focus", async () => {
    renderWorkspace(<SiteAccessibilityPage />);
    const trigger = await screen.findByRole("button", { name: "Run Accessibility Audit" });
    trigger.focus();
    fireEvent.click(trigger);
    const dialog = screen.getByRole("dialog", { name: "Run Accessibility Audit" });
    await waitFor(() => expect(dialog).toContainElement(document.activeElement as HTMLElement));
    fireEvent.keyDown(dialog, { key: "Escape" });
    expect(screen.queryByRole("dialog", { name: "Run Accessibility Audit" })).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });

  it("presents Needs Review separately from violations in rule evidence", async () => {
    api.getAccessibilityRules.mockResolvedValue({
      items: [{
        rule_id: "color-contrast",
        result_type: "incomplete",
        impact: "serious",
        help: "Elements must meet contrast thresholds",
        help_url: "https://dequeuniversity.com/rules/axe/4.12/color-contrast",
        tags: ["wcag2aa", "wcag143"],
        pages_affected: 2,
        affected_nodes: 4,
        profiles: ["desktop", "mobile"],
      }],
      total: 1,
      limit: 50,
      offset: 0,
    });
    renderWorkspace(<SiteAccessibilityPage />, "/sites/3/accessibility?view=rules");
    expect(await screen.findByText("Elements must meet contrast thresholds")).toBeInTheDocument();
    expect(screen.getAllByText("Needs Review").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Serious").length).toBeGreaterThan(0);
    expect(screen.getByText(/wcag2aa/)).toBeInTheDocument();
  });

  it("renders failed latest Page evidence without substituting old results", async () => {
    api.getAccessibilityPages.mockResolvedValue({
      items: [{ page_id: 8, page_url: "https://example.com/8", last_audited_at: "2026-08-13T12:00:00Z", desktop_outcome: "failed", mobile_outcome: "ready", desktop_violations: 0, mobile_violations: 2, critical_rules: 1, serious_rules: 0, needs_review_rules: 1 }],
      total: 1,
      limit: 100,
      offset: 0,
    });
    renderWorkspace(<SiteAccessibilityPage />, "/sites/3/accessibility?view=pages");
    const pageLink = await screen.findByRole("link", { name: "https://example.com/8" });
    expect(screen.getAllByText("Failed").length).toBeGreaterThan(0);
    expect(pageLink).toHaveAttribute("href", "/sites/3/pages/8?tab=accessibility");
  });

  it("renders raw detector text escaped and exposes provenance", async () => {
    api.getAccessibilityObservation.mockResolvedValue(observation());
    api.getAccessibilityPayload.mockResolvedValue('<img src=x onerror="alert(1)">{"safe":true}');
    renderWorkspace(<AccessibilityEvidencePage />, "/sites/3/accessibility/evidence/12", "accessibility/evidence/:observationId");
    expect(await screen.findByText(/<img src=x/)).toBeInTheDocument();
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
    expect(screen.getByText("4.12.1")).toBeInTheDocument();
    expect(screen.getByText("accessibility-normalization-v1")).toBeInTheDocument();
  });

  it("offers a one-Page audit with exact profile expansion", async () => {
    renderWorkspace(<PageAccessibilityPanel siteId="3" resourceId="8" />);
    fireEvent.click(await screen.findByRole("button", { name: "Audit this Page" }));
    expect(screen.getByText(/Pages ×/)).toHaveTextContent("1 Pages × 2 profiles = 2 browser audits");
    fireEvent.click(screen.getByRole("button", { name: "Start 2 audits" }));
    await waitFor(() => expect(api.createAccessibilityRun).toHaveBeenCalledWith("3", {
      resource_ids: [8], profiles: ["desktop", "mobile"], trigger: "page_workspace",
    }));
  });
});

function renderWorkspace(node: React.ReactNode, initial = "/sites/3/accessibility", childPath = "accessibility") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[initial]}><Routes><Route path="sites/:siteId" element={<Outlet context={{ site }} />}><Route path={childPath} element={node} /><Route path="accessibility/runs/:runId" element={<div>Run created</div>} /></Route></Routes></MemoryRouter></QueryClientProvider>);
}

function page(id: number) {
  return { resource_id: id, latest_title: `Page ${id}`, normalized_url: `https://example.com/${id}` };
}

function observation() {
  return {
    id: 12, accessibility_run_id: 4, website_property_id: 3, web_resource_id: 8,
    requested_url: "https://example.com/8", final_url: "https://example.com/8", profile: "desktop", outcome: "ready", observed_at: "2026-08-13T12:00:00Z",
    axe_core_version: "4.12.1", detector_bundle_sha256: "a".repeat(64), integration_version: "accessibility-engine-v1", normalization_version: "accessibility-normalization-v1",
    ruleset_profile: "wcag22-aa-v1", ruleset_sha256: "b".repeat(64), browser_engine: "chromium", browser_version: "151", playwright_version: "1.55",
    profile_json: {}, violation_rule_count: 1, violation_node_count: 1, incomplete_rule_count: 0, incomplete_node_count: 0, pass_rule_count: 20, inapplicable_rule_count: 40,
    normalized_sha256: "c".repeat(64), error_type: null, error_message: null, page_url: "https://example.com/8", payload_sha256: "d".repeat(64), payload_raw_byte_size: 100, payload_stored_byte_size: 80,
  };
}
