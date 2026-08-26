import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Outlet, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SiteRenderedPage } from "../src/pages/RenderedWorkspace";
import type { Site } from "../src/types/scans";

const api = vi.hoisted(() => ({
  listRenderRuns: vi.fn(),
  listSitePages: vi.fn(),
  createRenderRun: vi.fn(),
  getRenderCapabilities: vi.fn(),
}));

vi.mock("../src/api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../src/api/client")>()),
  ...api,
}));

const site = { id: 3, name: "Example", display_timezone: "UTC" } as Site;

describe("Rendered workspace", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.listRenderRuns.mockResolvedValue({ items: [], total: 0, limit: 25, offset: 0 });
    api.listSitePages.mockResolvedValue({
      items: [
        { resource_id: 8, latest_title: "About", normalized_url: "https://example.com/about" },
        { resource_id: 9, latest_title: "Contact", normalized_url: "https://example.com/contact" },
      ],
      total: 2,
      limit: 10,
      offset: 0,
    });
    api.createRenderRun.mockResolvedValue({ id: 41 });
    api.getRenderCapabilities.mockResolvedValue({
      defaults: {
        render_viewport_width: 1440,
        render_viewport_height: 900,
        render_navigation_timeout_seconds: 30,
        render_load_timeout_seconds: 5,
        render_color_scheme: "light",
        render_capture_full_page: true,
      },
      limits: {
        render_viewport_width: { minimum: 320, maximum: 3840 },
        render_viewport_height: { minimum: 240, maximum: 2160 },
        render_navigation_timeout_seconds: { minimum: 1, maximum: 120 },
        render_load_timeout_seconds: { minimum: 0, maximum: 30 },
      },
    });
  });

  afterEach(() => cleanup());

  it("selects a bounded Page set and queues one standalone Render Run", async () => {
    renderWorkspace();
    fireEvent.click(await screen.findByRole("button", { name: "Run renders" }));
    fireEvent.click(await screen.findByRole("checkbox", { name: /About/ }));
    fireEvent.click(screen.getByRole("checkbox", { name: /Contact/ }));
    fireEvent.change(screen.getByRole("spinbutton", { name: "Viewport width" }), { target: { value: "1280" } });
    fireEvent.click(screen.getByRole("button", { name: "Queue 2 Pages" }));
    await waitFor(() => expect(api.createRenderRun).toHaveBeenCalledWith("3", [8, 9], "site_workspace", { render_viewport_width: 1280 }));
    expect(await screen.findByText("Run created")).toBeInTheDocument();
  });
});

function renderWorkspace() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/sites/3/rendered"]}>
        <Routes>
          <Route path="sites/:siteId" element={<Outlet context={{ site }} />}>
            <Route path="rendered" element={<SiteRenderedPage />} />
            <Route path="rendered/runs/:runId" element={<div>Run created</div>} />
          </Route>
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}
