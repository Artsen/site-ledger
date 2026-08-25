import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Outlet, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AccessibilityObservationPage } from "../src/pages/AccessibilityObservationPage";
import { PerformanceObservationPage } from "../src/pages/PerformanceObservationPage";
import type { Site } from "../src/types/scans";

const api = vi.hoisted(() => ({
  getPerformanceObservationPresentation: vi.fn(),
  getAccessibilityObservation: vi.fn(),
  getAccessibilityObservationRules: vi.fn(),
  getAccessibilityObservationNodes: vi.fn(),
}));

vi.mock("../src/api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../src/api/client")>()),
  ...api,
}));

const site = { id: 3, name: "Example", display_timezone: "UTC" } as Site;

describe("human-readable observability details", () => {
  beforeEach(() => {
    api.getPerformanceObservationPresentation.mockResolvedValue({
      observation: performanceObservation({
        outcome: "unavailable",
        error_type: "no_field_data",
      }),
      metrics: [],
      opportunities: [],
      diagnostics: [],
      presentation_error: null,
      origin_context: performanceObservation({
        id: 13,
        target_kind: "origin",
        requested_target: "https://example.com",
        outcome: "ready",
      }),
      origin_metrics: [
        {
          key: "lcp",
          label: "Largest Contentful Paint",
          value: 2200,
          unit: "ms",
          formatted_value: "2.20 s",
          assessment: "good",
          histogram: [{ density: 0.8 }, { density: 0.15 }, { density: 0.05 }],
        },
      ],
    });
    api.getAccessibilityObservation.mockResolvedValue(
      accessibilityObservation(),
    );
    api.getAccessibilityObservationRules.mockResolvedValue({
      items: [
        {
          id: 31,
          accessibility_observation_id: 12,
          position: 0,
          rule_id: "button-name",
          result_type: "violation",
          impact: "critical",
          description: "Buttons need text",
          help: "Buttons must have discernible text",
          help_url: "https://dequeuniversity.com/rules/axe/4.12/button-name",
          tags_json: ["wcag2a", "wcag412"],
          node_count: 1,
          rule_evidence_sha256: "e".repeat(64),
        },
      ],
      total: 1,
      limit: 200,
      offset: 0,
    });
    api.getAccessibilityObservationNodes.mockResolvedValue({
      items: [
        {
          id: 51,
          position: 0,
          impact: "critical",
          target_json: ["#submit"],
          html_snippet: '<button id="submit"></button>',
          html_original_length: 29,
          html_truncated: false,
          failure_summary: "Fix the missing accessible name.",
          node_evidence_sha256: "f".repeat(64),
        },
      ],
      total: 1,
      limit: 25,
      offset: 0,
    });
  });

  afterEach(() => cleanup());

  it("presents unavailable URL evidence neutrally with same-run origin context", async () => {
    renderRoute(
      <PerformanceObservationPage />,
      "/sites/3/performance/observations/12",
      "performance/observations/:observationId",
    );
    expect(
      await screen.findByText("URL-level field data unavailable"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Site-origin context" }),
    ).toBeInTheDocument();
    expect(screen.getByText(/not Page-specific/)).toBeInTheDocument();
    expect(screen.getByText("80%")).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /View exact raw JSON/ }),
    ).toHaveAttribute("href", "/sites/3/performance/evidence/12");
  });

  it("explains unusable PageSpeed metrics while retaining raw evidence access", async () => {
    api.getPerformanceObservationPresentation.mockResolvedValue({
      observation: performanceObservation({
        provider: "pagespeed",
        provider_adapter_version: "pagespeed-provider-v2",
        dimension: "mobile",
        outcome: "failed",
        error_type: "no_usable_performance_metrics",
        error_message: "PageSpeed returned no usable Performance metrics.",
        normalized_sha256: null,
      }),
      metrics: [],
      opportunities: [],
      diagnostics: [],
      presentation_error: null,
      origin_context: null,
      origin_metrics: [],
    });

    renderRoute(
      <PerformanceObservationPage />,
      "/sites/3/performance/observations/12",
      "performance/observations/:observationId",
    );

    expect(
      await screen.findByText(
        "PageSpeed returned no usable Performance metrics.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /View exact raw JSON/ }),
    ).toHaveAttribute("href", "/sites/3/performance/evidence/12");
  });

  it("loads historical Accessibility nodes lazily and keeps raw evidence secondary", async () => {
    renderRoute(
      <AccessibilityObservationPage />,
      "/sites/3/accessibility/observations/12",
      "accessibility/observations/:observationId",
    );
    expect(
      await screen.findByRole("heading", { name: "Accessibility observation" }),
    ).toBeInTheDocument();
    expect(api.getAccessibilityObservationNodes).not.toHaveBeenCalled();
    fireEvent.click(
      screen.getByRole("button", {
        name: /Buttons must have discernible text/,
      }),
    );
    expect(
      await screen.findByText("Fix the missing accessible name."),
    ).toBeInTheDocument();
    expect(screen.getByText('["#submit"]')).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /View exact raw detector JSON/ }),
    ).toHaveAttribute("href", "/sites/3/accessibility/evidence/12");
    fireEvent.change(
      screen.getByRole("textbox", { name: "Search this observation" }),
      { target: { value: "not present" } },
    );
    expect(
      screen.queryByRole("button", {
        name: /Buttons must have discernible text/,
      }),
    ).not.toBeInTheDocument();
  });

  it("includes rules without an impact in the Unknown filter", async () => {
    api.getAccessibilityObservationRules.mockResolvedValue({
      items: [
        {
          id: 32,
          accessibility_observation_id: 12,
          position: 0,
          rule_id: "review-rule",
          result_type: "incomplete",
          impact: null,
          description: "Requires manual review",
          help: "Review this element",
          help_url: null,
          tags_json: [],
          node_count: 0,
          rule_evidence_sha256: "e".repeat(64),
        },
      ],
      total: 1,
      limit: 200,
      offset: 0,
    });
    renderRoute(
      <AccessibilityObservationPage />,
      "/sites/3/accessibility/observations/12",
      "accessibility/observations/:observationId",
    );
    expect(await screen.findByText("Review this element")).toBeInTheDocument();
    fireEvent.change(screen.getByRole("combobox", { name: "Impact" }), {
      target: { value: "unknown" },
    });
    expect(screen.getByText("Review this element")).toBeInTheDocument();
  });
});

function renderRoute(node: React.ReactNode, initial: string, path: string) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[initial]}>
        <Routes>
          <Route path="sites/:siteId" element={<Outlet context={{ site }} />}>
            <Route path={path} element={node} />
          </Route>
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function performanceObservation(overrides: Record<string, unknown> = {}) {
  return {
    id: 12,
    performance_run_id: 4,
    website_property_id: 3,
    web_resource_id: 8,
    provider: "crux",
    provider_adapter_version: "crux-provider-v1",
    normalization_version: "performance-normalization-v1",
    target_kind: "url",
    requested_target: "https://example.com/8",
    provider_target: "https://example.com/8",
    dimension: "PHONE",
    outcome: "ready",
    metrics_json: {},
    normalized_sha256: "b".repeat(64),
    provider_analysis_at: null,
    provider_period_json: null,
    provider_product_version: null,
    observed_at: "2026-08-13T12:00:00Z",
    error_type: null,
    error_message: null,
    page_url: "https://example.com/8",
    payload_sha256: "a".repeat(64),
    payload_raw_byte_size: 100,
    payload_stored_byte_size: 80,
    ...overrides,
  };
}

function accessibilityObservation() {
  return {
    id: 12,
    accessibility_run_id: 4,
    website_property_id: 3,
    web_resource_id: 8,
    requested_url: "https://example.com/8",
    final_url: "https://example.com/8",
    profile: "desktop",
    outcome: "ready",
    observed_at: "2026-08-13T12:00:00Z",
    axe_core_version: "4.12.1",
    detector_bundle_sha256: "a".repeat(64),
    integration_version: "accessibility-engine-v1",
    normalization_version: "accessibility-normalization-v1",
    ruleset_profile: "wcag22-aa-v1",
    ruleset_sha256: "b".repeat(64),
    browser_engine: "chromium",
    browser_version: "151",
    playwright_version: "1.55",
    profile_json: {},
    violation_rule_count: 1,
    violation_node_count: 1,
    incomplete_rule_count: 0,
    incomplete_node_count: 0,
    pass_rule_count: 20,
    inapplicable_rule_count: 40,
    normalized_sha256: "c".repeat(64),
    error_type: null,
    error_message: null,
    page_url: "https://example.com/8",
    payload_sha256: "d".repeat(64),
    payload_raw_byte_size: 100,
    payload_stored_byte_size: 80,
  };
}
