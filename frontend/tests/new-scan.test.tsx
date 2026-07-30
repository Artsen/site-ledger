import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it } from "vitest";

import { NewScanPage } from "../src/pages/NewScanPage";

afterEach(() => cleanup());

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

  it("preserves newlines in advanced list fields", () => {
    render(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter>
          <NewScanPage />
        </MemoryRouter>
      </QueryClientProvider>
    );
    fireEvent.click(screen.getByText("Advanced scope settings"));

    const allowedHosts = screen.getByLabelText("Allowed hosts");
    fireEvent.change(allowedHosts, { target: { value: "example.com\nblog.example.com" } });

    expect(allowedHosts).toHaveValue("example.com\nblog.example.com");
  });
});

