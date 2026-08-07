import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CategoryRuleHistoryPanel, CategoryRulesPanel } from "../src/components/CategoryRulesPanel";

const api = vi.hoisted(() => ({
  listCategoryRules: vi.fn(),
  previewCategoryRule: vi.fn(),
  createCategoryRule: vi.fn(),
  updateCategoryRule: vi.fn(),
  deleteCategoryRule: vi.fn(),
  getCategoryRuleDeletePreview: vi.fn(),
  evaluateCategoryRules: vi.fn(),
  listCategoryRuleRuns: vi.fn(),
}));

vi.mock("../src/api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../src/api/client")>()),
  ...api,
}));

const category = {
  id: 4,
  website_property_id: 1,
  name: "Blog",
  description: null,
  color_key: "blue",
  sort_order: 0,
  is_active: true,
  assignment_count: 0,
  manual_assignment_count: 0,
  automatic_assignment_count: 0,
  exclusion_count: 0,
  rule_count: 0,
  created_at: "2026-08-07T02:00:00Z",
  updated_at: "2026-08-07T02:00:00Z",
};

describe("Category Rules workspace", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.listCategoryRules.mockResolvedValue({ items: [], total: 0, limit: 25, offset: 0 });
    api.previewCategoryRule.mockResolvedValue({
      total_pages_evaluated: 3,
      matching_pages: 2,
      currently_assigned: 0,
      would_gain_automatic_support: 2,
      would_lose_automatic_support: 0,
      excluded_matches: 0,
      sample_matching_pages: [{ resource_id: 8, normalized_url: "https://example.com/blog/a" }],
      sample_non_matching_pages: [],
      invalid_conditions: [],
      evaluation_duration_ms: 2,
    });
    api.createCategoryRule.mockResolvedValue({ id: 1 });
    api.listCategoryRuleRuns.mockResolvedValue({ items: [], total: 0, limit: 25, offset: 0 });
  });

  it("builds, previews, and saves a Rule", async () => {
    renderPanel(<CategoryRulesPanel siteId="1" categories={[category]} timeZone="America/New_York" />);
    await screen.findByText("No Category Rules");
    fireEvent.click(screen.getByRole("button", { name: "Create Rule" }));
    fireEvent.change(screen.getByLabelText("Rule name"), { target: { value: "Blog paths" } });
    fireEvent.change(screen.getByLabelText("Rule Category"), { target: { value: "4" } });
    fireEvent.change(screen.getByLabelText("Condition 1 value"), { target: { value: "/blog/" } });
    fireEvent.click(screen.getByRole("button", { name: "Preview" }));
    expect(await screen.findByText("Preview: 2 matching Pages")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Save & Apply" }));
    await waitFor(() => expect(api.createCategoryRule).toHaveBeenCalled());
    expect(api.previewCategoryRule).toHaveBeenCalledWith("1", expect.objectContaining({ category_id: 4, match_mode: "all" }));
  });

  it("shows an empty evaluation history state", async () => {
    renderPanel(<CategoryRuleHistoryPanel siteId="1" timeZone="America/New_York" />);
    expect(await screen.findByText("No evaluations")).toBeInTheDocument();
  });
});

function renderPanel(node: React.ReactNode) {
  return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })}>{node}</QueryClientProvider>);
}
