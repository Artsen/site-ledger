import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { cancelScan, getScan, listErrors, listPages } from "../api/client";

const doneStatuses = new Set(["completed", "completed_with_errors", "failed", "cancelled", "interrupted"]);

export function ScanDetailPage() {
  const { scanId = "" } = useParams();
  const [tab, setTab] = useState("overview");
  const [search, setSearch] = useState("");
  const [errorState, setErrorState] = useState("any");
  const queryClient = useQueryClient();
  const scan = useQuery({
    queryKey: ["scan", scanId],
    queryFn: () => getScan(scanId),
    refetchInterval: (query) => (doneStatuses.has(query.state.data?.status ?? "") ? false : 1500)
  });
  const query = useMemo(() => {
    const params = new URLSearchParams();
    if (search) params.set("search", search);
    if (errorState !== "any") params.set("error_state", errorState);
    return `?${params.toString()}`;
  }, [search, errorState]);
  const pages = useQuery({ queryKey: ["pages", scanId, query], queryFn: () => listPages(scanId, query), refetchInterval: 2000 });
  const errors = useQuery({ queryKey: ["errors", scanId], queryFn: () => listErrors(scanId), enabled: tab === "errors" });
  const cancel = useMutation({
    mutationFn: () => cancelScan(scanId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["scan", scanId] })
  });

  if (scan.isLoading) return <div className="p-8">Loading scan...</div>;
  if (!scan.data) return <div className="p-8">Scan not found.</div>;

  return (
    <section className="px-8 py-7">
      <div className="mb-5 flex items-start justify-between gap-4">
        <div className="min-w-0">
          <h1 className="truncate text-xl font-semibold">{scan.data.starting_url}</h1>
          <div className="mt-1 text-sm text-stone-600">{scan.data.status}</div>
        </div>
        {!doneStatuses.has(scan.data.status) ? (
          <button onClick={() => cancel.mutate()} className="rounded-md border border-stone-300 px-3 py-2 text-sm">Cancel</button>
        ) : null}
      </div>
      <div className="mb-6 grid grid-cols-2 gap-3 md:grid-cols-5">
        <Metric label="Discovered" value={scan.data.discovered_count} />
        <Metric label="Fetched" value={scan.data.fetched_count} />
        <Metric label="Queued" value={scan.data.queued_count} />
        <Metric label="Errors" value={scan.data.failed_count} />
        <Metric label="Skipped" value={scan.data.skipped_count} />
      </div>
      <div className="mb-4 flex gap-2 border-b border-stone-200">
        {["overview", "pages", "errors"].map((item) => (
          <button key={item} onClick={() => setTab(item)} className={`px-3 py-2 text-sm ${tab === item ? "border-b-2 border-neutral-900 font-medium" : "text-stone-600"}`}>
            {item[0].toUpperCase() + item.slice(1)}
          </button>
        ))}
      </div>
      {tab === "overview" ? (
        <div className="space-y-4 text-sm">
          <div><span className="font-medium">Stop reason:</span> {scan.data.stop_reason ?? "Running"}</div>
          <pre className="overflow-auto rounded-md border border-stone-200 bg-white p-4 text-xs">{JSON.stringify(scan.data.scope_config, null, 2)}</pre>
          <RecentPages pages={pages.data?.items ?? []} scanId={scanId} />
        </div>
      ) : null}
      {tab === "pages" ? (
        <div>
          <div className="mb-3 flex flex-wrap gap-3">
            <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search URLs or titles" className="w-80 rounded-md border border-stone-300 bg-white px-3 py-2 text-sm" />
            <select value={errorState} onChange={(event) => setErrorState(event.target.value)} className="rounded-md border border-stone-300 bg-white px-3 py-2 text-sm">
              <option value="any">All states</option>
              <option value="with_errors">With errors</option>
              <option value="without_errors">Without errors</option>
            </select>
          </div>
          <PageTable scanId={scanId} pages={pages.data?.items ?? []} />
        </div>
      ) : null}
      {tab === "errors" ? (
        <div className="space-y-2">
          {errors.data?.map((error) => (
            <Link key={error.id} to={`/scans/${scanId}/pages/${error.id}`} className="block rounded-md border border-stone-200 bg-white p-3 text-sm">
              <span className="font-medium">{error.error_type}</span> {error.requested_url}
            </Link>
          ))}
        </div>
      ) : null}
    </section>
  );
}

function Metric({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-md border border-stone-200 bg-white px-4 py-3">
      <div className="text-xs uppercase tracking-wide text-stone-500">{label}</div>
      <div className="text-2xl font-semibold">{value}</div>
    </div>
  );
}

function RecentPages({ pages, scanId }: { pages: Array<{ id: number; requested_url: string; fetch_state: string }>; scanId: string }) {
  return (
    <div>
      <h2 className="mb-2 text-sm font-semibold">Recent pages</h2>
      <div className="space-y-1">
        {pages.slice(0, 8).map((page) => (
          <Link key={page.id} to={`/scans/${scanId}/pages/${page.id}`} className="block truncate rounded-md border border-stone-200 bg-white px-3 py-2">
            {page.requested_url} <span className="text-stone-500">{page.fetch_state}</span>
          </Link>
        ))}
      </div>
    </div>
  );
}

function PageTable({ pages, scanId }: { pages: Array<Record<string, unknown>>; scanId: string }) {
  return (
    <div className="overflow-auto rounded-md border border-stone-200 bg-white">
      <table className="min-w-full text-left text-sm">
        <thead className="bg-stone-100 text-xs uppercase text-stone-500">
          <tr>
            {["Requested URL", "Final URL", "Status", "Title", "Depth", "Content type", "Discovery source", "Inbound", "Duration", "Error"].map((header) => (
              <th key={header} className="whitespace-nowrap px-3 py-2 font-medium">{header}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {pages.map((page) => (
            <tr key={String(page.id)} className="border-t border-stone-100 hover:bg-stone-50">
              <td className="max-w-xs truncate px-3 py-2"><Link to={`/scans/${scanId}/pages/${String(page.id)}`} className="underline">{String(page.requested_url)}</Link></td>
              <td className="max-w-xs truncate px-3 py-2">{String(page.final_url ?? "")}</td>
              <td className="px-3 py-2">{String(page.http_status ?? "")}</td>
              <td className="max-w-xs truncate px-3 py-2">{String(page.title ?? "")}</td>
              <td className="px-3 py-2">{String(page.depth)}</td>
              <td className="max-w-xs truncate px-3 py-2">{String(page.content_type ?? "")}</td>
              <td className="max-w-xs truncate px-3 py-2">{String(page.discovery_source ?? "")}</td>
              <td className="px-3 py-2">{String(page.inbound_occurrence_count)}</td>
              <td className="px-3 py-2">{String(page.response_time_ms ?? "")}</td>
              <td className="px-3 py-2">{String(page.error_type ?? "")}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

