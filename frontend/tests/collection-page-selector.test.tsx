import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { CollectionPageSelector } from "../src/components/observability/CollectionPageSelector";

const api = vi.hoisted(() => ({ listSitePages: vi.fn() }));

vi.mock("../src/api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../src/api/client")>()),
  ...api,
}));

describe("CollectionPageSelector", () => {
  beforeEach(() => {
    api.listSitePages.mockImplementation((_siteId: string, query: string) => {
      const limit = Number(new URLSearchParams(query.slice(1)).get("limit"));
      const count = limit === 250 ? 250 : 10;
      return Promise.resolve({
        items: Array.from({ length: count }, (_, index) => page(index + 1)),
        total: 300,
        limit,
        offset: 0,
      });
    });
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("supports current-page and explicitly bounded matching selection", async () => {
    renderSelector(250);
    await screen.findByRole("checkbox", { name: /^Page 1 / });
    fireEvent.click(
      screen.getByRole("button", { name: "Select current page" }),
    );
    expect(screen.getByText(/10 of 250 Pages selected/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Clear selection" }));
    fireEvent.click(
      screen.getByRole("button", { name: "Select first 250 matching Pages" }),
    );
    await waitFor(() =>
      expect(screen.getByText(/250 of 250 Pages selected/)).toBeInTheDocument(),
    );
    expect(api.listSitePages).toHaveBeenCalledWith(
      "3",
      expect.stringContaining("limit=250"),
    );
  });

  it("preserves selections across search and enforces the hard cap", async () => {
    renderSelector(2);
    fireEvent.click(await screen.findByRole("checkbox", { name: /^Page 1 / }));
    fireEvent.change(
      screen.getByRole("textbox", { name: "Search Pages for Performance" }),
      {
        target: { value: "pricing" },
      },
    );
    expect(
      await screen.findByRole("checkbox", { name: /^Page 1 / }),
    ).toBeChecked();
    fireEvent.click(screen.getByRole("checkbox", { name: /^Page 2 / }));
    expect(screen.getByRole("checkbox", { name: /^Page 3 / })).toBeDisabled();
  });
});

function renderSelector(hardLimit: number) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  function Harness() {
    const [selected, setSelected] = useState<number[]>([]);
    return (
      <CollectionPageSelector
        siteId="3"
        selected={selected}
        hardLimit={hardLimit}
        label="Performance"
        onChange={setSelected}
      />
    );
  }
  return render(
    <QueryClientProvider client={client}>
      <Harness />
    </QueryClientProvider>,
  );
}

function page(id: number) {
  return {
    resource_id: id,
    latest_title: `Page ${id}`,
    normalized_url: `https://example.com/${id}`,
  };
}
