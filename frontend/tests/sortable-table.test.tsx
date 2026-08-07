import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { SortableTableHeader } from "../src/components/ui/SortableTableHeader";
import { useTableSort } from "../src/utils/useTableSort";

const rows = [
  { name: "Page 10", count: 10 },
  { name: "page 2", count: 2 },
  { name: "Page 1", count: 1 },
];
const values = {
  name: (row: (typeof rows)[number]) => row.name,
  count: (row: (typeof rows)[number]) => row.count,
};

function Fixture() {
  const { sortedItems, sort, changeSort } = useTableSort(rows, values);
  return <table><thead><tr><SortableTableHeader column="name" label="Name" activeColumn={sort?.column ?? null} direction={sort?.direction ?? null} onChange={changeSort} /><SortableTableHeader column="count" label="Count" activeColumn={sort?.column ?? null} direction={sort?.direction ?? null} onChange={changeSort} /></tr></thead><tbody>{sortedItems.map((row) => <tr key={row.count}><td>{row.name}</td><td>{row.count}</td></tr>)}</tbody></table>;
}

describe("sortable table headers", () => {
  afterEach(cleanup);

  it("sorts text naturally, marks the active heading, and restores default order", () => {
    render(<Fixture />);
    fireEvent.click(screen.getByRole("button", { name: "Sort Name ascending" }));
    expect(screen.getAllByRole("row").slice(1).map((row) => row.textContent)).toEqual(["Page 11", "page 22", "Page 1010"]);
    expect(screen.getByRole("columnheader", { name: /Name/ })).toHaveAttribute("aria-sort", "ascending");
    fireEvent.click(screen.getByRole("button", { name: "Restore default Name ordering" }));
    expect(screen.getAllByRole("row").slice(1).map((row) => row.textContent)).toEqual(["Page 1010", "page 22", "Page 11"]);
  });

  it("sorts numeric values numerically in both directions", () => {
    render(<Fixture />);
    fireEvent.click(screen.getByRole("button", { name: "Sort Count ascending" }));
    expect(screen.getAllByRole("row").slice(1).map((row) => row.lastElementChild?.textContent)).toEqual(["1", "2", "10"]);
    fireEvent.click(screen.getByRole("button", { name: "Sort Count descending" }));
    expect(screen.getAllByRole("row").slice(1).map((row) => row.lastElementChild?.textContent)).toEqual(["10", "2", "1"]);
  });
});
