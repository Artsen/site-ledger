import { useMemo, useState } from "react";

import type { SortDirection } from "../components/ui/SortableTableHeader";

export type SortValue = string | number | boolean | Date | null | undefined;
export type TableSortState<Key extends string> = {
  column: Key;
  direction: SortDirection;
} | null;

const collator = new Intl.Collator(undefined, {
  numeric: true,
  sensitivity: "base",
});

export function useTableSort<Item, Key extends string>(
  items: Item[],
  values: Record<Key, (item: Item) => SortValue>,
) {
  const [sort, setSort] = useState<TableSortState<Key>>(null);
  const sortedItems = useMemo(() => {
    if (!sort) return items;
    const getter = values[sort.column];
    return items
      .map((item, index) => ({ item, index }))
      .sort((left, right) => {
        const comparison = compareSortValues(getter(left.item), getter(right.item));
        if (comparison === 0) return left.index - right.index;
        return sort.direction === "asc" ? comparison : -comparison;
      })
      .map(({ item }) => item);
  }, [items, sort, values]);

  const changeSort = (column: string | null, direction: SortDirection | null) => {
    setSort(column && direction ? { column: column as Key, direction } : null);
  };

  return { sortedItems, sort, changeSort };
}

export function compareSortValues(left: SortValue, right: SortValue) {
  if (left == null && right == null) return 0;
  if (left == null) return 1;
  if (right == null) return -1;
  const normalizedLeft = left instanceof Date ? left.getTime() : left;
  const normalizedRight = right instanceof Date ? right.getTime() : right;
  if (typeof normalizedLeft === "number" && typeof normalizedRight === "number") {
    return normalizedLeft - normalizedRight;
  }
  if (typeof normalizedLeft === "boolean" && typeof normalizedRight === "boolean") {
    return Number(normalizedLeft) - Number(normalizedRight);
  }
  return collator.compare(String(normalizedLeft), String(normalizedRight));
}
