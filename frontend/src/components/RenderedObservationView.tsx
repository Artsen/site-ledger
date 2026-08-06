import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { getRenderedConsole, getRenderedErrors, getRenderedNetwork, renderedArtifactUrl } from "../api/client";
import type { RenderedObservation } from "../types/scans";
import { formatBytes, formatDate, formatStatus } from "../utils/format";
import { DefinitionList } from "./ui/DefinitionList";
import { EmptyState } from "./ui/EmptyState";
import { LoadingBlock } from "./ui/Loading";
import { PaginatedTableControls } from "./ui/PaginatedTableControls";
import { StatusBadge } from "./ui/StatusBadge";
import { useUrlPagination } from "../utils/useUrlPagination";

type Tab = "overview" | "screenshots" | "dom" | "network" | "console" | "errors";

export function RenderedObservationView({ observation }: { observation: RenderedObservation }) {
  const [tab, setTab] = useState<Tab>("overview");
  const networkPagination = useUrlPagination({ prefix: "network" });
  const consolePagination = useUrlPagination({ prefix: "console" });
  const errorPagination = useUrlPagination({ prefix: "page_errors" });
  const network = useQuery({ queryKey: ["rendered-network", observation.id, networkPagination.limit, networkPagination.offset], queryFn: () => getRenderedNetwork(observation.id, `?limit=${networkPagination.limit}&offset=${networkPagination.offset}`), enabled: tab === "network", placeholderData: (previous) => previous });
  const consoleMessages = useQuery({ queryKey: ["rendered-console", observation.id, consolePagination.limit, consolePagination.offset], queryFn: () => getRenderedConsole(observation.id, `?limit=${consolePagination.limit}&offset=${consolePagination.offset}`), enabled: tab === "console", placeholderData: (previous) => previous });
  const errors = useQuery({ queryKey: ["rendered-errors", observation.id, errorPagination.limit, errorPagination.offset], queryFn: () => getRenderedErrors(observation.id, `?limit=${errorPagination.limit}&offset=${errorPagination.offset}`), enabled: tab === "errors", placeholderData: (previous) => previous });
  useEffect(() => networkPagination.ensureValid(network.data?.total), [network.data?.total, networkPagination]);
  useEffect(() => consolePagination.ensureValid(consoleMessages.data?.total), [consoleMessages.data?.total, consolePagination]);
  useEffect(() => errorPagination.ensureValid(errors.data?.total), [errorPagination, errors.data?.total]);
  const domArtifact = observation.artifacts.find((item) => item.artifact_type === "rendered_dom");
  const dom = useQuery({ queryKey: ["rendered-dom", domArtifact?.id], queryFn: async () => (await fetch(renderedArtifactUrl(domArtifact!.id))).text(), enabled: tab === "dom" && Boolean(domArtifact) });
  const tabs: Array<[Tab, string]> = [["overview", "Overview"], ["screenshots", "Screenshots"], ["dom", "DOM"], ["network", `Network (${observation.network_entry_count})`], ["console", `Console (${observation.console_message_count})`], ["errors", `Errors (${observation.page_error_count})`]];
  return <div className="space-y-4">
    <div className="flex flex-wrap gap-2 border-b border-stone-200 pb-3">{tabs.map(([id, label]) => <button key={id} type="button" onClick={() => setTab(id)} className={`rounded-md px-3 py-2 text-sm ${tab === id ? "bg-neutral-900 text-white" : "bg-stone-100 text-stone-700"}`}>{label}</button>)}</div>
    {tab === "overview" ? <DefinitionList items={[
      { label: "Capture state", value: <StatusBadge status={observation.capture_state} /> },
      { label: "Requested URL", value: observation.requested_url }, { label: "Final URL", value: observation.final_url },
      { label: "Navigation status", value: observation.navigation_http_status }, { label: "Document title", value: observation.document_title },
      { label: "Captured", value: formatDate(observation.finished_at) }, { label: "Duration", value: observation.duration_ms == null ? null : `${observation.duration_ms} ms` },
      { label: "Browser", value: `${observation.browser_engine} ${observation.browser_version ?? ""}` }, { label: "Viewport", value: `${observation.viewport_width} x ${observation.viewport_height} @ ${observation.device_scale_factor}` },
      { label: "Readiness", value: observation.readiness_state }, { label: "Blocked requests", value: observation.blocked_request_count },
      { label: "Network bytes", value: formatBytes(observation.total_encoded_network_bytes) }, { label: "Error", value: observation.error_message ?? "None" }
    ]} /> : null}
    {tab === "overview" && observation.warnings_json.length ? <section><h3 className="mb-2 text-sm font-semibold">Warnings</h3><ul className="space-y-2 text-sm">{observation.warnings_json.map((warning, index) => <li key={index} className="rounded-md border border-amber-200 bg-amber-50 p-3"><strong>{formatStatus(warning.type ?? "warning")}</strong>: {warning.message}</li>)}</ul></section> : null}
    {tab === "screenshots" ? <div className="grid gap-4 lg:grid-cols-2">{observation.artifacts.filter((item) => item.artifact_type.includes("screenshot")).map((item) => <figure key={item.id} className="overflow-hidden rounded-md border border-stone-200 bg-white"><img src={renderedArtifactUrl(item.id)} alt={`${formatStatus(item.artifact_type)} capture`} className="h-auto w-full" loading="lazy" /><figcaption className="p-2 text-xs text-stone-600">{formatStatus(item.artifact_type)} · {item.width} x {item.height} · {formatBytes(item.raw_byte_size)}</figcaption></figure>)}</div> : null}
    {tab === "dom" ? !domArtifact ? <EmptyState title="No rendered DOM" message="The DOM was omitted or capture did not reach the artifact phase." /> : dom.isLoading ? <LoadingBlock label="Loading rendered DOM..." /> : <pre className="max-h-[70vh] overflow-auto whitespace-pre-wrap rounded-md border border-stone-200 bg-stone-950 p-4 text-xs text-stone-100">{dom.data}</pre> : null}
    {tab === "network" ? network.isLoading ? <LoadingBlock label="Loading browser network entries..." /> : <PaginatedDataTable headers={["Method", "URL", "Type", "Status", "Bytes", "Policy"]} rows={(network.data?.items ?? []).map((item) => [item.method, item.redacted_url, item.resource_type, item.response_status, formatBytes(item.encoded_data_length), item.policy_reason])} total={network.data?.total ?? 0} pagination={networkPagination} itemLabel="network entry" loading={network.isFetching} /> : null}
    {tab === "console" ? consoleMessages.isLoading ? <LoadingBlock label="Loading console messages..." /> : <PaginatedDataTable headers={["Type", "Message", "Source", "Offset"]} rows={(consoleMessages.data?.items ?? []).map((item) => [item.message_type, item.text, item.source_url, item.timestamp_offset_ms == null ? null : `${item.timestamp_offset_ms} ms`])} total={consoleMessages.data?.total ?? 0} pagination={consolePagination} itemLabel="console message" loading={consoleMessages.isFetching} /> : null}
    {tab === "errors" ? errors.isLoading ? <LoadingBlock label="Loading page errors..." /> : <PaginatedDataTable headers={["Name", "Message", "Source", "Offset"]} rows={(errors.data?.items ?? []).map((item) => [item.error_name, item.message, item.source_url, item.timestamp_offset_ms == null ? null : `${item.timestamp_offset_ms} ms`])} total={errors.data?.total ?? 0} pagination={errorPagination} itemLabel="Page error" loading={errors.isFetching} /> : null}
  </div>;
}

function PaginatedDataTable({ headers, rows, total, pagination, itemLabel, loading }: { headers: string[]; rows: Array<Array<string | number | null | undefined>>; total: number; pagination: ReturnType<typeof useUrlPagination>; itemLabel: string; loading: boolean }) {
  const controls = <PaginatedTableControls total={total} limit={pagination.limit} offset={pagination.offset} onPageChange={pagination.setPage} onPageSizeChange={pagination.setPageSize} itemLabel={itemLabel} isLoading={loading} compact />;
  return <div className="space-y-4">{controls}<DataTable headers={headers} rows={rows} />{controls}</div>;
}

function DataTable({ headers, rows }: { headers: string[]; rows: Array<Array<string | number | null | undefined>> }) {
  if (!rows.length) return <EmptyState title="No entries" message="No evidence was recorded for this category." />;
  return <div className="overflow-x-auto rounded-md border border-stone-200"><table className="min-w-full text-left text-sm"><thead className="bg-stone-100"><tr>{headers.map((header) => <th key={header} className="px-3 py-2">{header}</th>)}</tr></thead><tbody>{rows.map((row, index) => <tr key={index} className="border-t border-stone-100">{row.map((value, cell) => <td key={cell} className="max-w-xl break-all px-3 py-2">{value ?? "Not available"}</td>)}</tr>)}</tbody></table></div>;
}
