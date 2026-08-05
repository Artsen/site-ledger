import { useQuery } from "@tanstack/react-query";
import { Link, useParams, useSearchParams } from "react-router-dom";

import { getSitePage, listPageObservations } from "../api/client";
import { Button } from "../components/ui/Button";
import { DefinitionList } from "../components/ui/DefinitionList";
import { EmptyState } from "../components/ui/EmptyState";
import { ErrorBanner } from "../components/ui/ErrorBanner";
import { LoadingBlock } from "../components/ui/Loading";
import { StatusBadge } from "../components/ui/StatusBadge";
import type { PageObservation } from "../types/scans";
import { formatDate, formatStatus, plural } from "../utils/format";

export function PersistentPageDetailPage() {
  const { siteId = "", resourceId = "" } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  const query = new URLSearchParams();
  for (const key of ["scope", "offset"]) {
    const value = searchParams.get(key);
    if (value) query.set(key, value);
  }
  const page = useQuery({
    queryKey: ["site-page", siteId, resourceId],
    queryFn: () => getSitePage(siteId, resourceId)
  });
  const observations = useQuery({
    queryKey: ["site-page-observations", siteId, resourceId, query.toString()],
    queryFn: () => listPageObservations(siteId, resourceId, `?${query.toString()}`)
  });

  if (page.isLoading) return <PageFrame><LoadingBlock label="Loading Page..." /></PageFrame>;
  if (page.error) return <PageFrame><ErrorBanner error={page.error} title="Could not load Page" /></PageFrame>;
  if (!page.data) return <PageFrame><EmptyState title="Page not found" message="This Page has not been observed for the selected site." /></PageFrame>;

  return (
    <PageFrame>
      <div className="mb-5">
        <div className="mb-2 text-sm text-stone-500"><Link to={`/sites/${siteId}?tab=pages`} className="underline">{page.data.site_name}</Link> / Pages</div>
        <h1 className="break-all text-2xl font-semibold">{page.data.page.normalized_url}</h1>
        <div className="mt-2 text-sm text-stone-600">{plural(page.data.page.observation_count, "observation")}</div>
      </div>
      <div className="grid grid-cols-1 gap-5 xl:grid-cols-[360px_minmax(0,1fr)]">
        <section className="rounded-md border border-stone-200 bg-white p-4 shadow-sm">
          <h2 className="mb-4 text-base font-semibold">Page summary</h2>
          <DefinitionList items={[
            { label: "Normalized URL", value: page.data.page.normalized_url, copyValue: page.data.page.normalized_url },
            { label: "Host", value: page.data.page.host },
            { label: "Path", value: page.data.page.path },
            { label: "Query", value: page.data.page.query || "None" },
            { label: "First observed", value: formatDate(page.data.page.first_observed_at) },
            { label: "Latest observed", value: formatDate(page.data.page.latest_observed_at) },
            { label: "Latest retrieval", value: retrievalLabel(page.data.page.latest_retrieval_method) },
            { label: "Latest parse", value: parseLabel(page.data.page.latest_parse_method) },
            { label: "Reused from snapshot", value: page.data.page.latest_reused_from_snapshot_id ? String(page.data.page.latest_reused_from_snapshot_id) : "Not reused" }
          ]} />
        </section>
        <section className="rounded-md border border-stone-200 bg-white p-4 shadow-sm">
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
            <h2 className="text-base font-semibold">Observation history</h2>
            <select aria-label="Observation scope" value={searchParams.get("scope") ?? "site"} onChange={(event) => setObservationParam(setSearchParams, "scope", event.target.value)} className="rounded-md border border-stone-300 px-3 py-2 text-sm">
              <option value="site">This site</option>
              <option value="all">All sites</option>
            </select>
          </div>
          {observations.error ? <ErrorBanner error={observations.error} title="Could not load observations" /> : null}
          {observations.isLoading ? <LoadingBlock label="Loading observations..." /> : null}
          {observations.data?.items.length ? <ObservationTable observations={observations.data.items} /> : !observations.isLoading ? <EmptyState title="No observations" message="No scan observations were found for this Page." /> : null}
          {observations.data ? <Pagination total={observations.data.total} limit={observations.data.limit} offset={observations.data.offset} searchParams={searchParams} setSearchParams={setSearchParams} /> : null}
        </section>
      </div>
    </PageFrame>
  );
}

function ObservationTable({ observations }: { observations: PageObservation[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="min-w-full text-left text-sm">
        <thead className="bg-stone-100 text-xs uppercase text-stone-500">
          <tr>{["Observation", "Effective status", "Retrieval", "Parse", "Bytes", "Actions"].map((header) => <th key={header} scope="col" className="px-3 py-2">{header}</th>)}</tr>
        </thead>
        <tbody>
          {observations.map((observation) => (
            <tr key={observation.snapshot_id} className="border-t border-stone-100 align-top">
              <td className="max-w-md px-3 py-2">
                <span className="block font-medium">{observation.page_title ?? "Untitled"}</span>
                <span className="block text-xs text-stone-500">{formatDate(observation.observed_at)} - scan {observation.scan_id}</span>
                <span className="block truncate font-mono text-xs text-stone-500">{observation.final_url ?? observation.requested_url}</span>
              </td>
              <td className="px-3 py-2">{observation.http_status ? <StatusBadge status={String(observation.http_status)} label={String(observation.http_status)} /> : formatStatus(observation.fetch_state)}</td>
              <td className="px-3 py-2">
                <span className="block">{retrievalLabel(observation.retrieval_method)}</span>
                {observation.retrieval_http_status ? <span className="block text-xs text-stone-500">retrieval {observation.retrieval_http_status}</span> : null}
                {observation.reused_from_snapshot_id ? <span className="block text-xs text-stone-500">from snapshot {observation.reused_from_snapshot_id}</span> : null}
              </td>
              <td className="px-3 py-2">
                <span className="block">{parseLabel(observation.parse_method)}</span>
                {observation.parser_version ? <span className="block text-xs text-stone-500">{observation.parser_version}</span> : null}
              </td>
              <td className="px-3 py-2">{observation.network_bytes_transferred ?? "Unknown"}</td>
              <td className="px-3 py-2">
                <div className="flex flex-col gap-1 text-xs">
                  <Link className="underline" to={`/scans/${observation.scan_id}`}>Open scan</Link>
                  <Link className="underline" to={`/scans/${observation.scan_id}/pages/${observation.snapshot_id}`}>Open observation</Link>
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function PageFrame({ children }: { children: React.ReactNode }) {
  return <section className="mx-auto max-w-7xl px-4 py-6 sm:px-6 lg:px-8">{children}</section>;
}

function Pagination({ total, limit, offset, searchParams, setSearchParams }: { total: number; limit: number; offset: number; searchParams: URLSearchParams; setSearchParams: ReturnType<typeof useSearchParams>[1] }) {
  return (
    <div className="mt-4 flex flex-wrap items-center justify-between gap-3 text-sm text-stone-600">
      <span>{plural(total, "observation")}</span>
      <div className="flex gap-2">
        <Button type="button" disabled={offset <= 0} onClick={() => setOffset(setSearchParams, searchParams, Math.max(0, offset - limit))}>Previous</Button>
        <Button type="button" disabled={offset + limit >= total} onClick={() => setOffset(setSearchParams, searchParams, offset + limit)}>Next</Button>
      </div>
    </div>
  );
}

function setObservationParam(setSearchParams: ReturnType<typeof useSearchParams>[1], key: string, value: string) {
  setSearchParams((current) => {
    const next = new URLSearchParams(current);
    next.set(key, value);
    next.delete("offset");
    return next;
  });
}

function setOffset(setSearchParams: ReturnType<typeof useSearchParams>[1], searchParams: URLSearchParams, offset: number) {
  setSearchParams(() => {
    const next = new URLSearchParams(searchParams);
    next.set("offset", String(offset));
    return next;
  });
}

function retrievalLabel(value: string | null) {
  const labels: Record<string, string> = {
    full_fetch: "Full download",
    full_fetch_after_revalidation_fallback: "Full download",
    conditional_not_modified: "Revalidated unchanged",
    non_html: "Non-HTML",
    failed: "Failed"
  };
  return value ? labels[value] ?? value : "Legacy observation";
}

function parseLabel(value: string | null) {
  const labels: Record<string, string> = {
    parsed: "Full parse",
    reused_exact_hash: "Parsed result reused",
    reused_not_modified: "Parsed result reused",
    not_applicable: "No parse",
    failed: "Parse failed"
  };
  return value ? labels[value] ?? value : "Legacy parse state";
}
