import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { NewScanPage } from "../src/pages/NewScanPage";

describe("NewScanPage", () => {
  it("renders the PR 1 scan controls", () => {
    render(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter>
          <NewScanPage />
        </MemoryRouter>
      </QueryClientProvider>
    );
    expect(screen.getByLabelText("Starting URL")).toBeInTheDocument();
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
    expect(screen.getByText(/limited to the starting URL's hostname/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Start scan" })).toBeInTheDocument();
  });
});

