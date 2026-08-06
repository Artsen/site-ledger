import { useCallback, useEffect, useMemo } from "react";
import { useSearchParams } from "react-router-dom";

import { TABLE_PAGE_SIZES, finalValidOffset, pageToOffset, paginationState, withPaginationParams } from "./pagination";

type Options = {
  prefix: string;
  total?: number;
  defaultLimit?: number;
  allowedPageSizes?: readonly number[];
};

export function useUrlPagination({ prefix, total, defaultLimit = 50, allowedPageSizes = TABLE_PAGE_SIZES }: Options) {
  const [searchParams, setSearchParams] = useSearchParams();
  const limitKey = `${prefix}_limit`;
  const offsetKey = `${prefix}_offset`;
  const requestedLimit = Number(searchParams.get(limitKey) ?? defaultLimit);
  const limit = allowedPageSizes.includes(requestedLimit) ? requestedLimit : defaultLimit;
  const requestedOffset = Number(searchParams.get(offsetKey) ?? 0);
  const offset = Number.isFinite(requestedOffset) && requestedOffset >= 0 ? Math.floor(requestedOffset / limit) * limit : 0;
  const state = useMemo(() => paginationState(total ?? 0, limit, offset), [limit, offset, total]);

  const update = useCallback((nextLimit: number, nextOffset: number) => setSearchParams((current) =>
    withPaginationParams(current, prefix, nextLimit, nextOffset)
  ), [prefix, setSearchParams]);

  useEffect(() => {
    if (total === undefined) return;
    const corrected = total === 0 ? 0 : finalValidOffset(total, limit);
    if (offset > corrected) update(limit, corrected);
  }, [limit, offset, total, update]);

  const setPage = useCallback((page: number) => update(limit, total === undefined
    ? (Math.max(1, page) - 1) * limit
    : pageToOffset(page, limit, total)), [limit, total, update]);
  const setPageSize = useCallback((size: number) => update(allowedPageSizes.includes(size) ? size : defaultLimit, 0), [allowedPageSizes, defaultLimit, update]);
  const resetOffset = useCallback(() => update(limit, 0), [limit, update]);
  const ensureValid = useCallback((nextTotal: number | undefined) => {
    if (nextTotal === undefined) return;
    const corrected = nextTotal === 0 ? 0 : finalValidOffset(nextTotal, limit);
    if (offset > corrected) update(limit, corrected);
  }, [limit, offset, update]);

  return useMemo(() => ({
    ...state,
    limit,
    offset,
    limitKey,
    offsetKey,
    setPage,
    setPageSize,
    resetOffset,
    ensureValid,
  }), [ensureValid, limit, limitKey, offset, offsetKey, resetOffset, setPage, setPageSize, state]);
}
