import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { listSitePages } from "../../api/client";
import { Button } from "../ui/Button";
import { ErrorBanner } from "../ui/ErrorBanner";
import { LoadingBlock } from "../ui/Loading";
import { PaginatedTableControls } from "../ui/PaginatedTableControls";

type Props = {
  siteId: string;
  selected: number[];
  hardLimit: number;
  label: string;
  onChange: (selected: number[]) => void;
};

const PAGE_SIZE = 10;

export function CollectionPageSelector({
  siteId,
  selected,
  hardLimit,
  label,
  onChange,
}: Props) {
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [selectingMatching, setSelectingMatching] = useState(false);
  const pages = useQuery({
    queryKey: ["observability-page-selector", siteId, search, page],
    queryFn: () =>
      listSitePages(
        siteId,
        `?search=${encodeURIComponent(search)}&limit=${PAGE_SIZE}&offset=${(page - 1) * PAGE_SIZE}&sort=url&direction=asc`,
      ),
  });
  const remaining = Math.max(hardLimit - selected.length, 0);
  const currentIds = pages.data?.items.map((item) => item.resource_id) ?? [];
  const currentUnselected = currentIds.filter((id) => !selected.includes(id));
  const selectCurrent = () =>
    onChange([...selected, ...currentUnselected.slice(0, remaining)]);
  const selectMatching = async () => {
    if (!remaining) return;
    setSelectingMatching(true);
    try {
      const matches = await listSitePages(
        siteId,
        `?search=${encodeURIComponent(search)}&limit=${Math.min(remaining, 250)}&offset=0&sort=url&direction=asc`,
      );
      onChange([
        ...selected,
        ...matches.items
          .map((item) => item.resource_id)
          .filter((id) => !selected.includes(id))
          .slice(0, remaining),
      ]);
    } finally {
      setSelectingMatching(false);
    }
  };
  const toggle = (id: number) =>
    onChange(
      selected.includes(id)
        ? selected.filter((value) => value !== id)
        : selected.length < hardLimit
          ? [...selected, id]
          : selected,
    );
  const matchingCount = pages.data?.total ?? 0;
  const boundedMatchingCount = Math.min(matchingCount, remaining);

  return (
    <div className="space-y-3">
      <input
        aria-label={`Search Pages for ${label}`}
        value={search}
        onChange={(event) => {
          setSearch(event.target.value);
          setPage(1);
        }}
        placeholder="Search known Pages"
        className="w-full rounded-md border border-stone-300 px-3 py-2 text-sm"
      />
      <div className="flex flex-wrap gap-2">
        <Button
          type="button"
          disabled={!currentUnselected.length || !remaining}
          onClick={selectCurrent}
        >
          Select current page
        </Button>
        <Button
          type="button"
          loading={selectingMatching}
          disabled={!boundedMatchingCount}
          onClick={() => void selectMatching()}
        >
          Select first {boundedMatchingCount} matching Pages
        </Button>
        <Button
          type="button"
          disabled={!selected.length}
          onClick={() => onChange([])}
        >
          Clear selection
        </Button>
      </div>
      {pages.isLoading ? (
        <LoadingBlock label="Loading Pages..." />
      ) : pages.error ? (
        <ErrorBanner error={pages.error} title="Could not load Pages" />
      ) : (
        <>
          <div className="divide-y rounded-md border border-stone-200">
            {pages.data?.items.map((item) => (
              <label
                key={item.resource_id}
                className="flex cursor-pointer items-start gap-3 p-3 hover:bg-stone-50"
              >
                <input
                  type="checkbox"
                  className="mt-1"
                  checked={selected.includes(item.resource_id)}
                  disabled={!selected.includes(item.resource_id) && !remaining}
                  onChange={() => toggle(item.resource_id)}
                />
                <span className="min-w-0">
                  <span className="block truncate font-medium">
                    {item.latest_title ?? "Untitled Page"}
                  </span>
                  <span className="block truncate font-mono text-xs text-stone-500">
                    {item.normalized_url}
                  </span>
                </span>
              </label>
            ))}
          </div>
          {pages.data ? (
            <PaginatedTableControls
              compact
              total={pages.data.total}
              limit={PAGE_SIZE}
              offset={(page - 1) * PAGE_SIZE}
              onPageChange={setPage}
              onPageSizeChange={() => undefined}
              allowedPageSizes={[PAGE_SIZE]}
              itemLabel="Page"
            />
          ) : null}
        </>
      )}
      <p className="text-xs text-stone-600">
        {selected.length} of {hardLimit} Pages selected. Matching selection is
        explicitly bounded by the remaining capacity.
      </p>
    </div>
  );
}
