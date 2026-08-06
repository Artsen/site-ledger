# Table pagination

Server-paginated tables use the shared `PaginatedTableControls` component and
`useUrlPagination` hook. Major tables render the complete controls above and below
the rows. The controls show a bounded numbered window, result range, first/last and
previous/next actions, and a row-count selector.

Supported row counts are 25, 50, 100, and 250. Most tables default to 50; existing
catalogs that deliberately default to 25 retain that default. The API validates a
hard maximum of 250 rows through the shared `PageLimit` query type.

Pagination remains offset-based and URL-backed. Independently paginated views use
prefixed keys such as `pages_limit`, `pages_offset`, `resources_limit`, and
`resources_offset`. Updating one prefix preserves the active tab, filters, sort,
and other table prefixes. Filter and sort changes reset only the affected offset.
Changing row count resets that table to offset zero.

After a response changes the total, the hook corrects an out-of-range offset to the
final valid page. Tables that already retain TanStack Query placeholder data keep
their rows visible and disable navigation while the replacement request is active.

On desktop, the bounded numbered window is visible. Small screens retain the row
selector, Previous and Next actions, and a current-page indicator; First, Last, and
the numbered window collapse to prevent horizontal navigation overflow.
