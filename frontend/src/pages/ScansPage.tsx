import { useQuery } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";

import { listScanHistory } from "../api/client";
import { Button } from "../components/ui/Button";
import { EmptyState } from "../components/ui/EmptyState";
import { ErrorBanner } from "../components/ui/ErrorBanner";
import { LoadingBlock } from "../components/ui/Loading";
import { StatusBadge } from "../components/ui/StatusBadge";
import { formatDate, hostnameFromUrl, plural } from "../utils/format";

export function ScansPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const limit = Number(searchParams.get("limit") ?? 25);
  const offset = Number(searchParams.get("offset") ?? 0);
  const query = `?limit=${limit}&offset=${offset}`;
  const scans = useQuery({ queryKey: ["scan-history", query], queryFn: () => listScanHistory(query) });

  return (
    <section className="mx-auto max-w-7xl px-4 py-6 sm:px-6 lg:px-8">
      <div className="mb-5 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <div className="text-sm text-stone-500">Scans</div>
          <h1 className="mt-1 text-2xl font-semibold text-stone-950">Scan history</h1>
        </div>
        <Link to="/scans/new" className="rounded-md border border-neutral-900 bg-neutral-900 px-3 py-2 text-sm font-medium text-white hover:bg-neutral-700 focus:outline-none focus:ring-2 focus:ring-neutral-900 focus:ring-offset-2">
          New scan
        </Link>
      </div>
      {scans.error ? <ErrorBanner error={scans.error} title="Could not load scan history" /> : null}
      {scans.isLoading ? <LoadingBlock label="Loading scan history..." /> : null}
      {!scans.isLoading && !scans.data?.items.length ? <EmptyState title="No scans yet" message="Create a scan to start building history." /> : null}
      {scans.data?.items.length ? (
        <div className="overflow-x-auto rounded-md border border-stone-200 bg-white shadow-sm">
          <table className="min-w-full text-left text-sm">
            <thead className="bg-stone-100 text-xs uppercase text-stone-500">
              <tr>
                {["Host", "Status", "Created", "Pages", "Errors", "Actions"].map((header) => (
                  <th key={header} scope="col" className="px-3 py-2 font-medium">{header}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {scans.data.items.map((scan) => (
                <tr key={scan.id} className="border-t border-stone-100">
                  <td className="max-w-md px-3 py-2">
                    <Link to={`/scans/${scan.id}`} className="block truncate font-medium text-stone-950 underline" title={scan.starting_url}>
                      {hostnameFromUrl(scan.starting_url)}
                    </Link>
                    <span className="block truncate font-mono text-xs text-stone-500">{scan.starting_url}</span>
                  </td>
                  <td className="px-3 py-2"><StatusBadge status={scan.status} /></td>
                  <td className="px-3 py-2">{formatDate(scan.created_at)}</td>
                  <td className="px-3 py-2">{scan.fetched_count}/{scan.discovered_count}</td>
                  <td className="px-3 py-2">{scan.failed_count}</td>
                  <td className="px-3 py-2">
                    <Link to={`/scans/${scan.id}`} className="text-sm font-medium underline">Open</Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
      {scans.data ? (
        <div className="mt-4 flex flex-wrap items-center justify-between gap-3 text-sm text-stone-600">
          <span>{plural(scans.data.total, "scan")}</span>
          <div className="flex gap-2">
            <Button type="button" disabled={offset <= 0} onClick={() => setSearchParams({ limit: String(limit), offset: String(Math.max(0, offset - limit)) })}>Previous</Button>
            <Button type="button" disabled={offset + limit >= scans.data.total} onClick={() => setSearchParams({ limit: String(limit), offset: String(offset + limit) })}>Next</Button>
          </div>
        </div>
      ) : null}
    </section>
  );
}
