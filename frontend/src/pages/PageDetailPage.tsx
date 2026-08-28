import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";

import { getHtml, getInboundLinks, getLinks, getRenderedObservation, getSnapshot, getSnapshotStructuredContent, getSnapshotStructuredDocument, getSnapshotStructuredMarkdown, getStaticFetchAttempts, prepareSnapshotStructuredContent } from "../api/client";
import { RenderedObservationView } from "../components/RenderedObservationView";
import { StructuredContentView } from "../components/StructuredContentView";
import { LinkRoleBadge } from "../components/PageOrganization";
import { Button } from "../components/ui/Button";
import { CopyButton } from "../components/ui/CopyButton";
import { DefinitionList } from "../components/ui/DefinitionList";
import { EmptyState } from "../components/ui/EmptyState";
import { ErrorBanner } from "../components/ui/ErrorBanner";
import { LoadingBlock } from "../components/ui/Loading";
import { PaginatedTableControls } from "../components/ui/PaginatedTableControls";
import { StatusBadge } from "../components/ui/StatusBadge";
import { SortableTableHeader, type SortDirection } from "../components/ui/SortableTableHeader";
import { Tabs } from "../components/ui/Tabs";
import { UrlText } from "../components/ui/UrlText";
import { inputClass } from "../components/ui/styles";
import type { InboundLinkList, InboundLinkOccurrence, LinkOccurrence, Snapshot, StaticFetchAttempt } from "../types/scans";
import { formatBytes, formatDate, formatScopeDecision, formatStatus } from "../utils/format";
import { useDocumentTitle } from "../utils/useDocumentTitle";
import { useUrlPagination } from "../utils/useUrlPagination";
import { useTableSort } from "../utils/useTableSort";

export function PageDetailPage() {
  const { scanId = "", snapshotId = "" } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  const tab = searchParams.get("tab") ?? "overview";
  const snapshot = useQuery({ queryKey: ["snapshot", snapshotId], queryFn: () => getSnapshot(snapshotId) });
  useDocumentTitle(snapshot.data?.page_title ?? "Page");
  const links = useQuery({ queryKey: ["links", snapshotId], queryFn: () => getLinks(snapshotId), enabled: tab === "links" });
  const inboundQuery = useMemo(() => buildInboundQuery(searchParams), [searchParams]);
  const inboundLinks = useQuery({ queryKey: ["inbound-links", snapshotId, inboundQuery], queryFn: () => getInboundLinks(snapshotId, inboundQuery), enabled: tab === "inbound" });
  const html = useQuery({ queryKey: ["html", snapshotId], queryFn: () => getHtml(snapshotId), enabled: tab === "html" });
  const rendered = useQuery({ queryKey: ["rendered", snapshotId], queryFn: () => getRenderedObservation(snapshotId), retry: false });
  const attempts = useQuery({ queryKey: ["static-fetch-attempts", snapshotId], queryFn: () => getStaticFetchAttempts(snapshotId) });

  if (snapshot.isLoading) return <PageFrame><LoadingBlock label="Loading page..." /></PageFrame>;
  if (snapshot.error) return <PageFrame><ErrorBanner error={snapshot.error} title="Could not load page snapshot" /></PageFrame>;
  if (!snapshot.data) return <PageFrame><EmptyState title="Page not found" message="The snapshot may have been deleted or is unavailable." /></PageFrame>;

  const tabs = [
    { id: "overview", label: "Overview" },
    { id: "head", label: "Head" },
    { id: "links", label: "Outgoing links", count: links.data?.length },
    { id: "inbound", label: "Inbound links", count: inboundLinks.data?.summary.total_occurrences },
    { id: "content", label: "Content" },
    { id: "html", label: "HTML" },
    ...(rendered.data ? [{ id: "rendered", label: "Rendered" }] : [])
  ];
  const pageUrl = snapshot.data.final_url ?? snapshot.data.requested_url;
  const workspaceUrl = snapshot.data.is_html_page && snapshot.data.has_persistent_page && snapshot.data.website_property_id
    ? `/sites/${snapshot.data.website_property_id}/pages/${snapshot.data.resource_id}`
    : null;
  const pageLabel = snapshot.data.page_title ?? snapshot.data.requested_url;

  return (
    <PageFrame>
      <div className="mb-5">
        <div className="mb-2 text-sm text-stone-500">
          <Link to={`/scans/${scanId}`} className="underline">Scan</Link> / <Link to={`/scans/${scanId}?tab=pages`} className="underline">Pages</Link> / Observation
        </div>
        <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
          <div className="min-w-0">
            <h1 className="truncate text-xl font-semibold text-stone-950">{snapshot.data.page_title ?? snapshot.data.requested_url}</h1>
            <div className="mt-2 min-w-0"><UrlText value={pageUrl} secondary /></div>
            {workspaceUrl ? <div className="mt-2 truncate text-sm text-stone-600">Page workspace: <Link to={workspaceUrl} className="font-medium underline">{pageLabel}</Link></div> : null}
          </div>
          <div data-testid="observation-header-actions" className="flex flex-wrap items-center gap-2 lg:justify-end">
            {workspaceUrl ? <Link aria-label={`Open Page workspace for ${pageLabel}`} to={workspaceUrl} className="rounded-md border border-neutral-900 bg-neutral-900 px-3 py-2 text-sm font-medium text-white hover:bg-neutral-700 focus:outline-none focus:ring-2 focus:ring-neutral-900 focus:ring-offset-2">Open Page workspace</Link> : null}
            <a href={pageUrl} target="_blank" rel="noreferrer" className="rounded-md border border-stone-300 bg-white px-3 py-2 text-sm font-medium hover:bg-stone-50 focus:outline-none focus:ring-2 focus:ring-neutral-900 focus:ring-offset-2">{snapshot.data.is_html_page ? "Open live Page" : "Open live Resource"}</a>
            <CopyButton value={pageUrl} label="Copy Page URL" />
            <Link to={`/scans/${scanId}?tab=pages`} className="rounded-md border border-stone-300 bg-white px-3 py-2 text-sm font-medium hover:bg-stone-50 focus:outline-none focus:ring-2 focus:ring-neutral-900 focus:ring-offset-2">Back to Scan Pages</Link>
          </div>
        </div>
      </div>

      <Tabs tabs={tabs} active={tab} onChange={(next) => setSearchParams(next === "overview" ? {} : { tab: next })} />

      <div className="mt-5">
        {tab === "overview" ? <Overview snapshot={snapshot.data} attempts={attempts.data ?? []} attemptsLoading={attempts.isLoading} /> : null}
        {tab === "head" ? <HeadView snapshot={snapshot.data} /> : null}
        {tab === "links" ? <LinksView links={links.data ?? []} loading={links.isLoading} error={links.error} /> : null}
        {tab === "inbound" ? <InboundLinksView inbound={inboundLinks.data} loading={inboundLinks.isLoading} error={inboundLinks.error} searchParams={searchParams} setSearchParams={setSearchParams} scanId={scanId} /> : null}
        {tab === "content" ? <StructuredContentView queryKey={["snapshot-structured-content", snapshotId]} load={() => getSnapshotStructuredContent(snapshotId)} prepare={() => prepareSnapshotStructuredContent(snapshotId)} loadDocument={() => getSnapshotStructuredDocument(snapshotId)} loadMarkdown={() => getSnapshotStructuredMarkdown(snapshotId)} /> : null}
        {tab === "html" ? <HtmlView html={html.data ?? ""} loading={html.isLoading} error={html.error} /> : null}
        {tab === "rendered" && rendered.data ? <RenderedObservationView observation={rendered.data} /> : null}
      </div>
    </PageFrame>
  );
}

function InboundLinksView({
  inbound,
  loading,
  error,
  searchParams,
  setSearchParams,
  scanId
}: {
  inbound?: InboundLinkList;
  loading: boolean;
  error: unknown;
  searchParams: URLSearchParams;
  setSearchParams: ReturnType<typeof useSearchParams>[1];
  scanId: string;
}) {
  const pagination = useUrlPagination({ prefix: "inbound", total: inbound?.total });
  if (error) return <ErrorBanner error={error} title="Could not load inbound links" />;
  if (loading) return <LoadingBlock label="Loading inbound links..." />;
  if (!inbound) return null;
  return (
    <div className="space-y-4">
      <section className="rounded-md border border-stone-200 bg-white p-4 shadow-sm">
        <h2 className="mb-3 text-base font-semibold">Inbound link summary</h2>
        <div className="grid grid-cols-2 gap-3 text-sm md:grid-cols-5">
          <Metric label="Occurrences" value={inbound.summary.total_occurrences} />
          <Metric label="Unique source pages" value={inbound.summary.unique_source_pages} />
          <Metric label="Anchor texts" value={inbound.summary.unique_anchor_texts} />
          <Metric label="Nofollow" value={inbound.summary.nofollow_occurrences} />
          <Metric label="Self links" value={inbound.summary.self_link_occurrences} />
        </div>
      </section>
      <section className="rounded-md border border-stone-200 bg-white p-4 shadow-sm">
        <div className="grid grid-cols-1 gap-3 md:grid-cols-5">
          <input aria-label="Search inbound links" value={searchParams.get("inbound_search") ?? ""} onChange={(event) => updateInboundParam(setSearchParams, "inbound_search", event.target.value || null)} placeholder="Search source, href, or anchor" className={`${inputClass()} md:col-span-2`} />
          <input aria-label="Inbound scope decision" value={searchParams.get("scope_decision") ?? ""} onChange={(event) => updateInboundParam(setSearchParams, "scope_decision", event.target.value || null)} placeholder="Scope decision" className={inputClass()} />
          <input aria-label="Inbound source status" type="number" value={searchParams.get("source_status") ?? ""} onChange={(event) => updateInboundParam(setSearchParams, "source_status", event.target.value || null)} placeholder="Source status" className={inputClass()} />
          <input aria-label="Inbound rel filter" value={searchParams.get("rel") ?? ""} onChange={(event) => updateInboundParam(setSearchParams, "rel", event.target.value || null)} placeholder="rel contains" className={inputClass()} />
          <select aria-label="Inbound link role" value={searchParams.get("link_role") ?? ""} onChange={(event) => updateInboundParam(setSearchParams, "link_role", event.target.value || null)} className={inputClass()}><option value="">All roles</option>{["navigation", "main_content", "footer", "sidebar", "breadcrumb", "header_utility", "download", "email", "telephone", "image", "unknown", "legacy_unclassified"].map((role) => <option key={role} value={role}>{formatStatus(role)}</option>)}</select>
        </div>
        <div className="mt-3">
          <Button type="button" variant="ghost" onClick={() => setSearchParams(tabOnly(searchParams, "inbound"))}>Clear filters</Button>
        </div>
      </section>
      <PaginatedTableControls total={inbound.total} limit={pagination.limit} offset={pagination.offset} onPageChange={pagination.setPage} onPageSizeChange={pagination.setPageSize} itemLabel="inbound occurrence" />
      {!inbound.items.length ? <EmptyState title={hasInboundFilters(searchParams) ? "No inbound links match" : "No inbound links"} message={hasInboundFilters(searchParams) ? "Clear filters or broaden the search." : "No pages in this scan link to this page."} /> : <InboundTable items={inbound.items} scanId={scanId} activeSort={searchParams.get("inbound_sort")} direction={searchParams.get("inbound_direction") as SortDirection | null} onSort={(column, direction) => setInboundSort(setSearchParams, column, direction)} />}
      <PaginatedTableControls total={inbound.total} limit={pagination.limit} offset={pagination.offset} onPageChange={pagination.setPage} onPageSizeChange={pagination.setPageSize} itemLabel="inbound occurrence" />
    </div>
  );
}

function Metric({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-md border border-stone-200 bg-stone-50 px-3 py-2">
      <div className="text-xs font-medium uppercase text-stone-500">{label}</div>
      <div className="mt-1 text-xl font-semibold">{value}</div>
    </div>
  );
}

function InboundTable({ items, scanId, activeSort, direction, onSort }: { items: InboundLinkOccurrence[]; scanId: string; activeSort: string | null; direction: SortDirection | null; onSort: (column: string | null, direction: SortDirection | null) => void }) {
  return (
    <div className="overflow-x-auto rounded-md border border-stone-200 bg-white shadow-sm">
      <table className="min-w-full text-left text-sm">
        <thead className="bg-stone-100 text-xs uppercase text-stone-500">
          <tr>{[["source_url", "Source page"], ["source_status", "Status"], ["source_depth", "Depth"], ["anchor_text", "Anchor text"], ["link_role", "Role"], ["raw_href", "Raw href"], ["rel", "rel"], ["scope_decision", "Scope decision"], ["discovered_at", "Provenance"]].map(([column, label]) => <SortableTableHeader key={column} column={column} label={label} activeColumn={activeSort} direction={direction} onChange={onSort} defaultDirection={column === "discovered_at" ? "desc" : "asc"} />)}</tr>
        </thead>
        <tbody>
          {items.map((link) => (
            <tr key={link.id} className="border-t border-stone-100 align-top">
              <td className="max-w-sm px-3 py-2">
                <Link to={`/scans/${scanId}/pages/${link.source_snapshot_id}`} className="block min-w-0 underline">
                  <span className="block truncate">{link.source_page_title || "Untitled source page"}</span>
                  <span className="block truncate font-mono text-xs text-stone-500">{link.source_final_url ?? link.source_requested_url}</span>
                </Link>
                {link.is_self_link ? <span className="mt-1 inline-block rounded-md bg-amber-50 px-2 py-0.5 text-xs text-amber-800">Self link</span> : null}
              </td>
              <td className="px-3 py-2">{link.source_http_status ?? "Not available"}</td>
              <td className="px-3 py-2">{link.source_crawl_depth}</td>
              <td className="max-w-xs px-3 py-2">
                {link.anchor_text || link.aria_label || link.title || <span className="text-stone-500">No visible anchor text</span>}
                {link.rel?.toLowerCase().includes("nofollow") ? <span className="mt-1 block rounded-md bg-stone-100 px-2 py-0.5 text-xs text-stone-700">nofollow</span> : null}
              </td>
              <td className="px-3 py-2"><LinkRoleBadge role={link.link_role} label={link.link_role_label} rule={link.link_role_rule} /></td>
              <td className="max-w-sm px-3 py-2"><UrlText value={link.raw_href} secondary /></td>
              <td className="max-w-xs px-3 py-2 text-xs text-stone-600">{link.rel ?? "None"}</td>
              <td className="px-3 py-2"><StatusBadge status={link.in_scope ? "completed" : "interrupted"} label={formatScopeDecision(link.scope_decision)} /></td>
              <td className="max-w-sm px-3 py-2 text-xs">
                <details>
                  <summary className="cursor-pointer font-medium text-stone-700">Details</summary>
                  <dl className="mt-2 space-y-1 text-stone-600">
                    <dt className="font-medium">Resolved URL</dt>
                    <dd><UrlText value={link.resolved_url} secondary /></dd>
                    <dt className="font-medium">DOM location</dt>
                    <dd className="break-all font-mono">{link.dom_path ?? "Not available"}</dd>
                    <dt className="font-medium">Attributes</dt>
                    <dd>{[link.target ? `target=${link.target}` : "", link.title ? `title=${link.title}` : "", link.aria_label ? `aria-label=${link.aria_label}` : ""].filter(Boolean).join(" | ") || "None"}</dd>
                    <dt className="font-medium">Discovered</dt>
                    <dd>{formatDate(link.discovered_at)}</dd>
                  </dl>
                </details>
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

function Overview({ snapshot, attempts, attemptsLoading }: { snapshot: Snapshot; attempts: StaticFetchAttempt[]; attemptsLoading: boolean }) {
  const attemptValues = { attempt: (item: StaticFetchAttempt) => item.attempt_number, outcome: (item: StaticFetchAttempt) => item.outcome, status: (item: StaticFetchAttempt) => item.retrieval_http_status, duration: (item: StaticFetchAttempt) => item.response_time_ms, transferred: (item: StaticFetchAttempt) => item.network_bytes_transferred, retry: (item: StaticFetchAttempt) => item.retry_reason, error: (item: StaticFetchAttempt) => item.error_type };
  const attemptSort = useTableSort(attempts, attemptValues);
  return (
    <div className="space-y-5">
      <PageWorkspaceRelationship snapshot={snapshot} />
      <section className="rounded-md border border-stone-200 bg-white p-4 shadow-sm">
        <h2 className="mb-4 text-base font-semibold">Page overview</h2>
        <DefinitionList
          items={[
            { label: "Requested URL", value: snapshot.requested_url, copyValue: snapshot.requested_url },
            { label: "Final URL", value: snapshot.final_url ?? "Same as requested", copyValue: snapshot.final_url },
            { label: "HTTP status", value: snapshot.http_status ? <StatusBadge status={String(snapshot.http_status)} label={String(snapshot.http_status)} /> : "Not available" },
            { label: "Fetch state", value: <StatusBadge status={snapshot.fetch_state} /> },
            { label: "Page title", value: snapshot.page_title ?? "Untitled" },
            { label: "Canonical URL", value: snapshot.canonical_url ?? "Not available", copyValue: snapshot.canonical_url },
            { label: "HTML language", value: snapshot.html_language },
            { label: "Meta robots", value: snapshot.meta_robots },
            { label: "Content type", value: snapshot.content_type },
            { label: "Encoding", value: snapshot.encoding },
            { label: "Crawl depth", value: snapshot.crawl_depth },
            { label: "Fetched", value: formatDate(snapshot.fetched_at) },
            { label: "Response time", value: snapshot.response_time_ms != null ? `${snapshot.response_time_ms} ms` : null },
            { label: "Raw HTML size", value: formatBytes(snapshot.html_raw_byte_size) },
            { label: "Compressed HTML size", value: formatBytes(snapshot.html_stored_byte_size) },
            { label: "Raw HTML SHA-256", value: snapshot.raw_html_sha256, copyValue: snapshot.raw_html_sha256 },
            { label: "Head SHA-256", value: snapshot.head_sha256, copyValue: snapshot.head_sha256 },
            { label: "Error type", value: snapshot.error_type ? formatStatus(snapshot.error_type) : "None" },
            { label: "Error message", value: snapshot.error_message ?? "None" }
          ]}
        />
      </section>
      <section className="rounded-md border border-stone-200 bg-white p-4 shadow-sm">
        <h2 className="mb-4 text-base font-semibold">Static fetch attempts</h2>
        {attemptsLoading ? <LoadingBlock label="Loading fetch attempts..." /> : !attempts.length ? <EmptyState title="No attempt history" message="This legacy snapshot predates durable static attempt evidence." /> : (
          <div className="overflow-x-auto">
            <table className="min-w-full text-left text-sm">
              <thead className="bg-stone-100 text-xs uppercase text-stone-500"><tr>{[["attempt", "Attempt"], ["outcome", "Outcome"], ["status", "Status"], ["duration", "Duration"], ["transferred", "Transferred"], ["retry", "Retry decision"], ["error", "Error"]].map(([column, label]) => <SortableTableHeader key={column} column={column} label={label} activeColumn={attemptSort.sort?.column ?? null} direction={attemptSort.sort?.direction ?? null} onChange={attemptSort.changeSort} />)}</tr></thead>
              <tbody>{attemptSort.sortedItems.map((attempt) => <tr key={attempt.id} className="border-t border-stone-100 align-top">
                <td className="px-3 py-2 font-medium">{attempt.attempt_number}</td>
                <td className="px-3 py-2"><StatusBadge status={attempt.outcome} /></td>
                <td className="px-3 py-2">{attempt.retrieval_http_status ?? "No response"}</td>
                <td className="px-3 py-2">{attempt.response_time_ms == null ? "Not available" : `${attempt.response_time_ms} ms`}</td>
                <td className="px-3 py-2">{formatBytes(attempt.network_bytes_transferred)}</td>
                <td className="px-3 py-2">{attempt.retryable ? formatStatus(attempt.retry_reason ?? "retryable") : "Not retryable"}</td>
                <td className="max-w-md px-3 py-2"><div>{attempt.error_type ? formatStatus(attempt.error_type) : "None"}</div>{attempt.error_message ? <div className="mt-1 break-words text-xs text-stone-600">{attempt.error_message}</div> : null}</td>
              </tr>)}</tbody>
            </table>
          </div>
        )}
      </section>
      <RedirectChain chain={snapshot.redirect_chain ?? []} />
    </div>
  );
}

function PageWorkspaceRelationship({ snapshot }: { snapshot: Snapshot }) {
  const workspaceUrl = snapshot.is_html_page && snapshot.has_persistent_page && snapshot.website_property_id
    ? `/sites/${snapshot.website_property_id}/pages/${snapshot.resource_id}`
    : null;
  return (
    <section aria-labelledby="page-workspace-relationship" className="rounded-md border border-stone-200 bg-white p-4 shadow-sm">
      <h2 id="page-workspace-relationship" className="text-base font-semibold">Page workspace</h2>
      {workspaceUrl ? <>
        <dl className="mt-3 grid gap-3 text-sm sm:grid-cols-3">
          <div><dt className="text-xs font-medium uppercase text-stone-500">Site</dt><dd className="mt-1">{snapshot.website_property_name ?? `Site ${snapshot.website_property_id}`}</dd></div>
          <div><dt className="text-xs font-medium uppercase text-stone-500">Persistent Page</dt><dd className="mt-1"><Link to={workspaceUrl} className="font-medium underline">Open {snapshot.page_title ?? "Page workspace"}</Link></dd></div>
          <div><dt className="text-xs font-medium uppercase text-stone-500">Resource identity</dt><dd className="mt-1 font-mono">#{snapshot.resource_id}</dd></div>
        </dl>
        <p className="mt-3 text-sm text-stone-600">This observation records what Site Ledger found during this Scan. The Page workspace contains Site-specific history, categories, notes, owner, and workflow status.</p>
      </> : !snapshot.is_html_page ? (
        <p className="mt-2 text-sm text-stone-600">This observation represents a non-HTML Resource and does not have a Page workspace. Use the Scan Resources or Site Resource history instead.</p>
      ) : snapshot.website_property_id == null ? (
        <p className="mt-2 text-sm text-stone-600">This observation came from an ad hoc Scan and has no Site-scoped Page workspace.</p>
      ) : (
        <p className="mt-2 text-sm text-amber-800">This historical observation belongs to {snapshot.website_property_name ?? `Site ${snapshot.website_property_id}`}, but its persistent Page workspace association is unavailable.</p>
      )}
    </section>
  );
}

function RedirectChain({ chain }: { chain: Array<Record<string, unknown>> }) {
  if (!chain.length) return <EmptyState title="No redirects recorded" message="The requested URL did not redirect before the final response." />;
  return (
    <section className="rounded-md border border-stone-200 bg-white p-4 shadow-sm">
      <h2 className="mb-4 text-base font-semibold">Redirect chain</h2>
      <ol className="space-y-3">
        {chain.map((hop, index) => (
          <li key={`${String(hop.requested_url)}-${index}`} className="rounded-md border border-stone-200 p-3 text-sm">
            <div className="mb-2 flex items-center gap-2">
              <span className="text-xs font-medium text-stone-500">Hop {index + 1}</span>
              <StatusBadge status={String(hop.status_code ?? "")} label={String(hop.status_code ?? "Redirect")} />
            </div>
            <DefinitionList
              items={[
                { label: "Source URL", value: String(hop.requested_url ?? "Not available"), copyValue: typeof hop.requested_url === "string" ? hop.requested_url : null },
                { label: "Raw Location", value: String(hop.location ?? "Not available"), copyValue: typeof hop.location === "string" ? hop.location : null },
                { label: "Resolved destination", value: String(hop.resolved_url ?? "Not available"), copyValue: typeof hop.resolved_url === "string" ? hop.resolved_url : null }
              ]}
            />
          </li>
        ))}
      </ol>
    </section>
  );
}

function HeadView({ snapshot }: { snapshot: Snapshot }) {
  const head = snapshot.parsed_head_json ?? {};
  const meta = getArrayRecords(head.meta);
  const links = getArrayRecords(head.links);
  const jsonLd = getStringArray(head.json_ld);
  const openGraph = getRecord(head.open_graph);
  const twitter = getRecord(head.twitter);
  return (
    <div className="space-y-5">
      <section className="rounded-md border border-stone-200 bg-white p-4 shadow-sm">
        <h2 className="mb-4 text-base font-semibold">Basic metadata</h2>
        <DefinitionList
          items={[
            { label: "Title", value: snapshot.page_title ?? "Untitled" },
            { label: "Meta description", value: snapshot.meta_description },
            { label: "HTML language", value: snapshot.html_language },
            { label: "Character encoding", value: snapshot.encoding ?? String(head.encoding ?? "Not available") },
            { label: "Viewport", value: String(head.viewport ?? "Not available") },
            { label: "Meta robots", value: snapshot.meta_robots },
            { label: "Canonical URL", value: snapshot.canonical_url, copyValue: snapshot.canonical_url }
          ]}
        />
      </section>
      <KeyValueSection title="Open Graph" values={openGraph} />
      <KeyValueSection title="Twitter metadata" values={twitter} />
      <RecordTable title="Head links" records={links} columns={["rel", "href", "hreflang", "media", "type", "sizes"]} />
      <RecordTable title="Other meta elements" records={meta} columns={["name", "property", "content", "http-equiv"]} />
      <JsonLdSection blocks={jsonLd} />
      <details className="rounded-md border border-stone-200 bg-white p-4 shadow-sm">
        <summary className="cursor-pointer text-sm font-medium">Raw parsed head JSON</summary>
        <pre className="mt-3 max-h-96 overflow-auto rounded-md border border-stone-200 bg-stone-50 p-3 text-xs">{JSON.stringify(head, null, 2)}</pre>
      </details>
    </div>
  );
}

function KeyValueSection({ title, values }: { title: string; values: Record<string, unknown> }) {
  const entries = Object.entries(values);
  if (!entries.length) return <EmptyState title={`No ${title}`} message="This page did not include these fields." />;
  return (
    <section className="rounded-md border border-stone-200 bg-white p-4 shadow-sm">
      <h2 className="mb-4 text-base font-semibold">{title}</h2>
      <DefinitionList items={entries.map(([key, value]) => ({ label: key, value: String(value ?? "") }))} />
    </section>
  );
}

function RecordTable({ title, records, columns }: { title: string; records: Array<Record<string, unknown>>; columns: string[] }) {
  const values = Object.fromEntries(columns.map((column) => [column, (record: Record<string, unknown>) => String(record[column] ?? "")]));
  const recordSort = useTableSort(records, values);
  if (!records.length) return <EmptyState title={`No ${title.toLowerCase()}`} message="No matching elements were preserved in the parsed head." />;
  return (
    <section className="rounded-md border border-stone-200 bg-white p-4 shadow-sm">
      <h2 className="mb-4 text-base font-semibold">{title}</h2>
      <div className="overflow-x-auto">
        <table className="min-w-full text-left text-sm">
          <thead className="text-xs uppercase text-stone-500">
            <tr>{columns.map((column) => <SortableTableHeader key={column} column={column} label={column} activeColumn={recordSort.sort?.column ?? null} direction={recordSort.sort?.direction ?? null} onChange={recordSort.changeSort} />)}</tr>
          </thead>
          <tbody>
            {recordSort.sortedItems.map((record, index) => (
              <tr key={index} className="border-t border-stone-100">
                {columns.map((column) => <td key={column} className="max-w-md break-words px-3 py-2">{String(record[column] ?? "")}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function JsonLdSection({ blocks }: { blocks: string[] }) {
  if (!blocks.length) return <EmptyState title="No structured data" message="No JSON-LD blocks were found in the page head." />;
  return (
    <section className="rounded-md border border-stone-200 bg-white p-4 shadow-sm">
      <h2 className="mb-4 text-base font-semibold">Structured data</h2>
      <div className="space-y-3">
        {blocks.map((block, index) => {
          const parsed = tryPrettyJson(block);
          return (
            <div key={index} className="rounded-md border border-stone-200 p-3">
              <div className="mb-2 flex items-center justify-between gap-2">
                <span className="text-sm font-medium">JSON-LD block {index + 1}</span>
                <CopyButton value={block} label="Copy JSON-LD" />
              </div>
              {parsed.valid ? null : <div className="mb-2 text-sm text-amber-700">Invalid JSON preserved as source text.</div>}
              <pre className="max-h-96 overflow-auto whitespace-pre-wrap rounded-md bg-stone-50 p-3 text-xs">{parsed.value}</pre>
            </div>
          );
        })}
      </div>
    </section>
  );
}

function LinksView({ links, loading, error }: { links: LinkOccurrence[]; loading: boolean; error: unknown }) {
  const [search, setSearch] = useState("");
  const [decision, setDecision] = useState("all");
  const [inScopeOnly, setInScopeOnly] = useState(false);
  const [role, setRole] = useState("all");
  const filtered = links.filter((link) => {
    const haystack = [link.resolved_url, link.normalized_target_url, link.raw_href, link.anchor_text, link.scope_decision].join(" ").toLowerCase();
    return (!search || haystack.includes(search.toLowerCase())) && (decision === "all" || link.scope_decision === decision) && (role === "all" || (link.link_role ?? "legacy_unclassified") === role) && (!inScopeOnly || link.in_scope);
  });
  const linkValues = { destination: (link: LinkOccurrence) => link.resolved_url ?? link.normalized_target_url, anchor: (link: LinkOccurrence) => link.anchor_text ?? link.aria_label, role: (link: LinkOccurrence) => link.link_role, scope: (link: LinkOccurrence) => link.scope_decision, raw: (link: LinkOccurrence) => link.raw_href, attributes: (link: LinkOccurrence) => `${link.rel ?? ""} ${link.target ?? ""} ${link.title ?? ""}`, dom: (link: LinkOccurrence) => link.dom_path };
  const linkSort = useTableSort(filtered, linkValues);
  const decisions = Array.from(new Set(links.map((link) => link.scope_decision))).sort();
  if (error) return <ErrorBanner error={error} title="Could not load links" />;
  if (loading) return <LoadingBlock label="Loading links..." />;
  if (!links.length) return <EmptyState title="No link occurrences" message="No anchor links were preserved for this page snapshot." />;
  return (
    <div className="space-y-4">
      <div className="rounded-md border border-stone-200 bg-white p-4 shadow-sm">
        <div className="grid grid-cols-1 gap-3 md:grid-cols-4">
          <input aria-label="Search links" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search destination, href, or anchor text" className={inputClass()} />
          <select aria-label="Scope decision filter" value={decision} onChange={(event) => setDecision(event.target.value)} className={inputClass()}>
            <option value="all">All decisions</option>
            {decisions.map((item) => <option key={item} value={item}>{formatScopeDecision(item)}</option>)}
          </select>
          <select aria-label="Link role filter" value={role} onChange={(event) => setRole(event.target.value)} className={inputClass()}><option value="all">All roles</option>{["navigation", "main_content", "footer", "sidebar", "breadcrumb", "header_utility", "download", "email", "telephone", "image", "unknown", "legacy_unclassified"].map((item) => <option key={item} value={item}>{formatStatus(item)}</option>)}</select>
          <label className="flex items-center gap-2 rounded-md border border-stone-200 bg-white px-3 py-2 text-sm">
            <input type="checkbox" checked={inScopeOnly} onChange={(event) => setInScopeOnly(event.target.checked)} className="size-4 rounded border-stone-300 focus:ring-neutral-900" />
            In-scope only
          </label>
        </div>
      </div>
      {!filtered.length ? <EmptyState title="No links match these filters" message="Clear filters or broaden the search." /> : null}
      <div className="overflow-x-auto rounded-md border border-stone-200 bg-white shadow-sm">
        <table className="min-w-full text-left text-sm">
          <thead className="bg-stone-100 text-xs uppercase text-stone-500">
            <tr>{[["destination", "Destination"], ["anchor", "Anchor text"], ["role", "Role"], ["scope", "Scope decision"], ["raw", "Raw href"], ["attributes", "Attributes"], ["dom", "DOM path"]].map(([column, label]) => <SortableTableHeader key={column} column={column} label={label} activeColumn={linkSort.sort?.column ?? null} direction={linkSort.sort?.direction ?? null} onChange={linkSort.changeSort} />)}</tr>
          </thead>
          <tbody>
            {linkSort.sortedItems.map((link) => (
              <tr key={link.id} className="border-t border-stone-100 align-top">
                <td className="max-w-sm px-3 py-2"><UrlText value={link.resolved_url ?? link.normalized_target_url} /></td>
                <td className="max-w-xs px-3 py-2">
                  {link.anchor_text ? <span>{link.anchor_text}</span> : <span className="text-stone-500">No visible text</span>}
                  {!link.anchor_text && link.aria_label ? <span className="mt-1 block text-xs text-stone-600">aria-label: {link.aria_label}</span> : null}
                </td>
                <td className="px-3 py-2"><LinkRoleBadge role={link.link_role} label={link.link_role_label} rule={link.link_role_rule} /></td>
                <td className="px-3 py-2"><StatusBadge status={link.in_scope ? "completed" : "interrupted"} label={formatScopeDecision(link.scope_decision)} /></td>
                <td className="max-w-sm px-3 py-2"><UrlText value={link.raw_href} secondary /></td>
                <td className="max-w-xs px-3 py-2 text-xs text-stone-600">
                  {[link.rel ? `rel=${link.rel}` : "", link.target ? `target=${link.target}` : "", link.title ? `title=${link.title}` : "", link.exclusion_reason ? `reason=${link.exclusion_reason}` : ""].filter(Boolean).join(" | ") || "None"}
                </td>
                <td className="max-w-sm truncate px-3 py-2 font-mono text-xs" title={link.dom_path ?? ""}>{link.dom_path}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function HtmlView({ html, loading, error }: { html: string; loading: boolean; error: unknown }) {
  const [search, setSearch] = useState("");
  const [currentMatch, setCurrentMatch] = useState(0);
  const [wrap, setWrap] = useState(true);
  const lineRefs = useRef<Array<HTMLSpanElement | null>>([]);
  const matches = useMemo(() => {
    if (!search) return [];
    const lower = html.toLowerCase();
    const needle = search.toLowerCase();
    const found: number[] = [];
    let index = lower.indexOf(needle);
    while (index >= 0 && found.length < 1000) {
      found.push(index);
      index = lower.indexOf(needle, index + Math.max(needle.length, 1));
    }
    return found;
  }, [html, search]);
  const currentLine = useMemo(() => {
    const match = matches[currentMatch];
    if (match == null) return null;
    return html.slice(0, match).split(/\r?\n/).length - 1;
  }, [currentMatch, html, matches]);
  useEffect(() => {
    if (currentLine == null) return;
    lineRefs.current[currentLine]?.scrollIntoView({ block: "center" });
  }, [currentLine]);
  if (error) return <ErrorBanner error={error} title="Could not load HTML" />;
  if (loading) return <LoadingBlock label="Loading HTML source..." />;
  if (!html) return <EmptyState title="No HTML source" message="This snapshot does not have stored HTML." />;
  const lines = html.split(/\r?\n/);
  return (
    <div className="space-y-4">
      <div className="rounded-md border border-stone-200 bg-white p-4 shadow-sm">
        <div className="flex flex-wrap items-center gap-3">
          <input aria-label="Search HTML source" value={search} onChange={(event) => { setSearch(event.target.value); setCurrentMatch(0); }} placeholder="Search source" className={`${inputClass()} max-w-md`} />
          <span className="text-sm text-stone-600">{matches.length ? `${currentMatch + 1} of ${matches.length} matches` : search ? "No matches" : "No search"}</span>
          <Button type="button" disabled={!matches.length} onClick={() => setCurrentMatch((current) => Math.max(0, current - 1))}>Previous</Button>
          <Button type="button" disabled={!matches.length} onClick={() => setCurrentMatch((current) => Math.min(matches.length - 1, current + 1))}>Next</Button>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={wrap} onChange={(event) => setWrap(event.target.checked)} className="size-4 rounded border-stone-300 focus:ring-neutral-900" />
            Wrap lines
          </label>
          <CopyButton value={html} label="Copy source" />
        </div>
      </div>
      <pre
        aria-label="Escaped HTML source"
        className={`max-h-[70vh] overflow-auto rounded-md border border-stone-200 bg-white p-4 text-xs leading-5 shadow-sm ${wrap ? "whitespace-pre-wrap" : "whitespace-pre"}`}
      >
        {lines.map((line, index) => (
          <span key={index} ref={(element) => { lineRefs.current[index] = element; }} className={`block ${index === currentLine ? "bg-amber-50" : ""}`}>
            <span className="mr-4 inline-block w-10 select-none text-right text-stone-400">{index + 1}</span>
            <code>{line || " "}</code>
          </span>
        ))}
      </pre>
    </div>
  );
}

function getRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
}

function getArrayRecords(value: unknown): Array<Record<string, unknown>> {
  return Array.isArray(value) ? value.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object" && !Array.isArray(item)) : [];
}

function getStringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

function tryPrettyJson(value: string) {
  try {
    return { valid: true, value: JSON.stringify(JSON.parse(value), null, 2) };
  } catch {
    return { valid: false, value };
  }
}

function buildInboundQuery(searchParams: URLSearchParams) {
  const params = new URLSearchParams();
  const mappings: Array<[string, string]> = [
    ["inbound_search", "search"],
    ["scope_decision", "scope_decision"],
    ["source_status", "source_status"],
    ["rel", "rel"],
    ["link_role", "link_role"],
    ["inbound_sort", "sort"],
    ["inbound_direction", "direction"],
    ["inbound_limit", "limit"],
    ["inbound_offset", "offset"]
  ];
  for (const [from, to] of mappings) {
    const value = searchParams.get(from);
    if (value) params.set(to, value);
  }
  return `?${params.toString()}`;
}

function setInboundSort(setSearchParams: ReturnType<typeof useSearchParams>[1], column: string | null, direction: SortDirection | null) {
  setSearchParams((current) => {
    const next = new URLSearchParams(current);
    next.set("tab", "inbound");
    if (column && direction) { next.set("inbound_sort", column); next.set("inbound_direction", direction); }
    else { next.delete("inbound_sort"); next.delete("inbound_direction"); }
    next.delete("inbound_offset");
    return next;
  });
}

function updateInboundParam(setSearchParams: ReturnType<typeof useSearchParams>[1], key: string, value: string | null) {
  setSearchParams((current) => {
    const next = new URLSearchParams(current);
    next.set("tab", "inbound");
    if (value) next.set(key, value);
    else next.delete(key);
    next.delete("inbound_offset");
    return next;
  });
}

function tabOnly(searchParams: URLSearchParams, tab: string) {
  const next = new URLSearchParams(searchParams);
  for (const key of ["inbound_search", "scope_decision", "source_status", "rel", "link_role", "inbound_sort", "inbound_direction", "inbound_offset"]) {
    next.delete(key);
  }
  next.set("tab", tab);
  return next;
}

function hasInboundFilters(searchParams: URLSearchParams) {
  return ["inbound_search", "scope_decision", "source_status", "rel", "link_role"].some((key) => searchParams.has(key));
}
