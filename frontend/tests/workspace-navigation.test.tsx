import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AppShell } from "../src/components/AppShell";
import { LegacySiteRedirect } from "../src/pages/site-workspace/SiteWorkspacePages";
import {
  isSiteAreaActive,
  siteAreaFromPath,
  siteAreaHref,
  siteIdFromPath,
  switchSiteHref,
} from "../src/navigation/workspaceNavigation";

const api = vi.hoisted(() => ({ listSites: vi.fn(), listScanHistory: vi.fn() }));

vi.mock("../src/api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../src/api/client")>()),
  listSites: api.listSites,
  listScanHistory: api.listScanHistory,
}));

describe("workspace navigation contract", () => {
  beforeEach(() => {
    window.localStorage.clear();
    api.listSites.mockResolvedValue({
      items: [
        { id: 3, name: "Alpha", base_url: "https://alpha.example", total_scan_count: 0 },
        { id: 8, name: "Beta", base_url: "https://beta.example", total_scan_count: 0 },
      ],
      total: 2,
      limit: 100,
      offset: 0,
    });
    api.listScanHistory.mockResolvedValue({ items: [], total: 0, limit: 6, offset: 0 });
  });

  afterEach(() => cleanup());

  it("maps canonical and nested detail routes to one explicit Site area", () => {
    expect(siteIdFromPath("/sites/3/pages/92")).toBe("3");
    expect(siteAreaFromPath("/sites/3/pages/92")).toBe("pages");
    expect(siteAreaFromPath("/sites/3/comparisons/11/resources/9")).toBe("comparisons");
    expect(siteAreaFromPath("/sites/3/edit")).toBe("settings");
    expect(isSiteAreaActive("/sites/3/resources/7", 3, "resources")).toBe(true);
    expect(isSiteAreaActive("/sites/3/resources/7", 3, "overview")).toBe(false);
  });

  it("switches Sites at the conceptual area without leaking object IDs or query state", () => {
    expect(switchSiteHref("/sites/3/pages/92", 8)).toBe("/sites/8/pages");
    expect(switchSiteHref("/sites/3/comparisons/11/resources/9", 8)).toBe("/sites/8/comparisons");
    expect(switchSiteHref("/sites/3", 8)).toBe("/sites/8");
    expect(siteAreaHref(8, "category-rules")).toBe("/sites/8/category-rules");
  });

  it("persists desktop collapse preference", async () => {
    renderShell("/sites/3/pages");
    fireEvent.click(await screen.findByRole("button", { name: "Collapse sidebar" }));
    expect(window.localStorage.getItem("site-ledger.sidebar-collapsed")).toBe("true");
    expect(screen.getByRole("button", { name: "Expand sidebar" })).toBeInTheDocument();
  });

  it("ignores an invalid persisted collapse preference", () => {
    window.localStorage.setItem("site-ledger.sidebar-collapsed", "collapsed");
    renderShell("/sites/3/pages");
    expect(screen.getByRole("button", { name: "Collapse sidebar" })).toBeInTheDocument();
  });

  it("shows the current Site hostname and a catalog failure state", async () => {
    api.listSites.mockRejectedValueOnce(new Error("offline"));
    renderShell("/sites/3/pages");
    const switcher = await screen.findByRole("combobox", { name: "Current Site" });
    await waitFor(() => expect(screen.getByText("Could not load Sites")).toBeInTheDocument());
    expect(switcher).toBeDisabled();
  });

  it("handles an empty Site catalog without losing current route context", async () => {
    api.listSites.mockResolvedValueOnce({ items: [], total: 0, limit: 100, offset: 0 });
    renderShell("/sites/3/pages");
    const switcher = await screen.findByRole("combobox", { name: "Current Site" });
    await waitFor(() => expect(screen.getByRole("option", { name: "Site 3" })).toBeInTheDocument());
    expect(switcher).toBeDisabled();
  });

  it("opens and closes the mobile drawer with Escape and restores focus", async () => {
    renderShell("/sites/3/pages");
    const trigger = screen.getByRole("button", { name: "Open navigation" });
    fireEvent.click(trigger);
    expect(screen.getAllByRole("complementary", { name: "Workspace navigation" })).toHaveLength(2);
    fireEvent.keyDown(window, { key: "Escape" });
    await waitFor(() => expect(screen.getAllByRole("complementary", { name: "Workspace navigation" })).toHaveLength(1));
    expect(trigger).toHaveFocus();
  });

  it("switches from a nested Page to the other Site's Pages root", async () => {
    api.listSites.mockResolvedValueOnce({
      items: [
        { id: 3, name: "Alpha", base_url: "https://alpha.example", total_scan_count: 0 },
        { id: 8, name: "Beta", base_url: "https://beta.example", total_scan_count: 0 },
      ], total: 2, limit: 100, offset: 0,
    });
    renderShell("/sites/3/pages/92");
    const switcher = await screen.findByRole("combobox", { name: "Current Site" });
    await waitFor(() => expect(switcher).not.toBeDisabled());
    expect(screen.getByText("alpha.example")).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Beta" })).toHaveValue("8");
    fireEvent.change(switcher, { target: { value: "8" } });
    await waitFor(() => expect(screen.getByTestId("location")).toHaveTextContent("/sites/8/pages"));
  });

  it("migrates legacy tab URLs while retaining unrelated filter state", async () => {
    render(
      <MemoryRouter initialEntries={["/sites/3?tab=pages&search=pricing&site_pages_limit=100"]}>
        <Routes>
          <Route path="sites/:siteId" element={<LegacySiteRedirect />} />
          <Route path="sites/:siteId/pages" element={<Location />} />
        </Routes>
      </MemoryRouter>,
    );
    await waitFor(() => expect(screen.getByTestId("location")).toHaveTextContent("/sites/3/pages?search=pricing&site_pages_limit=100"));
  });
});

function renderShell(initialEntry: string) {
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter initialEntries={[initialEntry]}>
        <Routes>
          <Route path="/" element={<AppShell />}>
            <Route path="sites/:siteId/*" element={<Location />} />
          </Route>
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function Location() {
  const location = useLocation();
  return <div data-testid="location">{location.pathname}{location.search}</div>;
}
