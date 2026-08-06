import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { PaginatedTableControls } from "../src/components/ui/PaginatedTableControls";

afterEach(cleanup);

describe("PaginatedTableControls", () => {
  it("renders ranges, numbered pages, and boundary states", () => {
    const changePage = vi.fn();
    render(<PaginatedTableControls total={376} limit={50} offset={100} onPageChange={changePage} onPageSizeChange={vi.fn()} itemLabel="entry" />);
    expect(screen.getByText("Showing 101-150 of 376 entries")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Page 3" })).toHaveAttribute("aria-current", "page");
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(changePage).toHaveBeenCalledWith(4);
    expect(screen.getByRole("button", { name: "Previous" })).toBeEnabled();
  });

  it("supports all page sizes and resets through the size callback", () => {
    const changeSize = vi.fn();
    render(<PaginatedTableControls total={1_000} limit={50} offset={0} onPageChange={vi.fn()} onPageSizeChange={changeSize} itemLabel="Page" />);
    const select = screen.getByRole("combobox", { name: "Page rows per page" });
    expect([...select.querySelectorAll("option")].map((option) => option.value)).toEqual(["25", "50", "100", "250"]);
    fireEvent.change(select, { target: { value: "250" } });
    expect(changeSize).toHaveBeenCalledWith(250);
    expect(screen.getByRole("button", { name: "First" })).toBeDisabled();
  });
});
