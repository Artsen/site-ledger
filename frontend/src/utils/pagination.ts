export const TABLE_PAGE_SIZES = [25, 50, 100, 250] as const;

export type PageToken = number | "ellipsis-start" | "ellipsis-end";

export function paginationState(total: number, limit: number, offset: number) {
  const safeTotal = Math.max(0, total);
  const safeLimit = Math.max(1, limit);
  const totalPages = Math.max(1, Math.ceil(safeTotal / safeLimit));
  const currentPage = Math.min(totalPages, Math.max(1, Math.floor(Math.max(0, offset) / safeLimit) + 1));
  const firstVisibleItem = safeTotal ? (currentPage - 1) * safeLimit + 1 : 0;
  const lastVisibleItem = safeTotal ? Math.min(currentPage * safeLimit, safeTotal) : 0;
  return {
    currentPage,
    totalPages,
    firstVisibleItem,
    lastVisibleItem,
    canGoPrevious: currentPage > 1,
    canGoNext: currentPage < totalPages,
  };
}

export function pageTokens(totalPages: number, currentPage: number, radius = 2): PageToken[] {
  if (totalPages <= 1) return [1];
  const pages = new Set([1, totalPages]);
  for (let page = Math.max(1, currentPage - radius); page <= Math.min(totalPages, currentPage + radius); page += 1) pages.add(page);
  const ordered = [...pages].sort((a, b) => a - b);
  const tokens: PageToken[] = [];
  ordered.forEach((page, index) => {
    const previous = ordered[index - 1];
    if (previous && page - previous > 1) tokens.push(previous === 1 ? "ellipsis-start" : "ellipsis-end");
    tokens.push(page);
  });
  return tokens;
}

export function pageToOffset(page: number, limit: number, total: number) {
  const totalPages = Math.max(1, Math.ceil(Math.max(0, total) / Math.max(1, limit)));
  return (Math.min(totalPages, Math.max(1, page)) - 1) * Math.max(1, limit);
}

export function finalValidOffset(total: number, limit: number) {
  return pageToOffset(Math.max(1, Math.ceil(Math.max(0, total) / Math.max(1, limit))), limit, total);
}

export function withPaginationParams(current: URLSearchParams, prefix: string, limit: number, offset: number) {
  const next = new URLSearchParams(current);
  next.set(`${prefix}_limit`, String(limit));
  next.set(`${prefix}_offset`, String(Math.max(0, offset)));
  return next;
}
