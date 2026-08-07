import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";

import {
  createPageNote,
  addPageCategoryExclusion,
  getPageCategoryProvenance,
  getInboundLinks,
  getOutgoingLinks,
  getSitePage,
  listPageCategories,
  listPageNotes,
  listPageObservations,
  removePageCategoryExclusion,
  updatePageMetadata,
} from "../api/client";
import { NotesPanel } from "../components/NotesPanel";
import {
  LinkRoleBadge,
  PageCategoryBadges,
  WorkflowStatusBadge,
} from "../components/PageOrganization";
import { Button } from "../components/ui/Button";
import { CopyButton } from "../components/ui/CopyButton";
import { DefinitionList } from "../components/ui/DefinitionList";
import { EmptyState } from "../components/ui/EmptyState";
import { ErrorBanner } from "../components/ui/ErrorBanner";
import { LoadingBlock } from "../components/ui/Loading";
import { PaginatedTableControls } from "../components/ui/PaginatedTableControls";
import { StatusBadge } from "../components/ui/StatusBadge";
import { SortableTableHeader } from "../components/ui/SortableTableHeader";
import { Tabs } from "../components/ui/Tabs";
import type {
  LinkOccurrence,
  PageObservation,
  PersistentPageDetail,
} from "../types/scans";
import { formatDate, formatStatus, plural } from "../utils/format";
import { useDocumentTitle } from "../utils/useDocumentTitle";
import { useUrlPagination } from "../utils/useUrlPagination";
import { useTableSort } from "../utils/useTableSort";

const WORKFLOWS = [
  "unreviewed",
  "needs_review",
  "approved",
  "updating",
  "deprecated",
  "archived",
];

export function PersistentPageDetailPage() {
  const { siteId = "", resourceId = "" } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  const tab = searchParams.get("tab") ?? "overview";
  const page = useQuery({
    queryKey: ["site-page", siteId, resourceId],
    queryFn: () => getSitePage(siteId, resourceId),
  });
  useDocumentTitle(
    page.data?.page.latest_title ??
      (page.data ? page.data.page.normalized_url : "Page"),
  );
  if (page.isLoading)
    return (
      <PageFrame>
        <LoadingBlock label="Loading Page..." />
      </PageFrame>
    );
  if (page.error)
    return (
      <PageFrame>
        <ErrorBanner error={page.error} title="Could not load Page" />
      </PageFrame>
    );
  if (!page.data)
    return (
      <PageFrame>
        <EmptyState
          title="Page not found"
          message="This Page is not associated with the selected Site."
        />
      </PageFrame>
    );
  const value = page.data.page;
  return (
    <PageFrame>
      <header className="mb-5">
        <div className="mb-2 text-sm text-stone-500">
          <Link to={`/sites/${siteId}?tab=pages`} className="underline">
            {page.data.site_name}
          </Link>{" "}
          / Pages
        </div>
        <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
          <div className="min-w-0">
            <h1 className="truncate text-2xl font-semibold">
              {value.latest_title ?? "Untitled Page"}
            </h1>
            <p className="mt-1 break-all font-mono text-xs text-stone-600">
              {value.normalized_url}
            </p>
            <div className="mt-3 flex flex-wrap items-center gap-2">
              <WorkflowStatusBadge status={value.workflow_status} />
              <span className="text-sm">
                Owner: {value.owner_label ?? "Unassigned"}
              </span>
              <PageCategoryBadges categories={value.categories} />
              <span className="text-sm text-stone-500">
                {plural(value.observation_count, "Scan")}
              </span>
            </div>
          </div>
          <div className="flex gap-2">
            <a
              href={value.normalized_url}
              target="_blank"
              rel="noreferrer"
              className="rounded-md border border-stone-300 bg-white px-3 py-2 text-sm font-medium"
            >
              Open live URL
            </a>
            <CopyButton value={value.normalized_url} label="Copy URL" />
          </div>
        </div>
      </header>
      <Tabs
        tabs={[
          { id: "overview", label: "Overview" },
          { id: "scans", label: "Scans", count: value.observation_count },
          { id: "links", label: "Links" },
          { id: "browser", label: "Browser evidence" },
          { id: "notes", label: "Notes", count: value.note_count },
        ]}
        active={tab}
        onChange={(next) => setTab(setSearchParams, next)}
      />
      <div className="mt-5">
        {tab === "overview" ? <OverviewTab detail={page.data} /> : null}
        {tab === "scans" ? (
          <ScansTab siteId={siteId} resourceId={resourceId} />
        ) : null}
        {tab === "links" ? <LinksTab detail={page.data} /> : null}
        {tab === "browser" ? <BrowserEvidenceTab siteId={siteId} resourceId={resourceId} /> : null}
        {tab === "notes" ? (
          <NotesPanel
            queryKey={["page-notes", siteId, resourceId]}
            list={(query) => listPageNotes(siteId, resourceId, query)}
            create={(body, pinned) =>
              createPageNote(siteId, resourceId, body, pinned)
            }
            context={`this Page within ${page.data.site_name}`}
          />
        ) : null}
      </div>
    </PageFrame>
  );
}

function OverviewTab({ detail }: { detail: PersistentPageDetail }) {
  const [editing, setEditing] = useState(false);
  const queryClient = useQueryClient();
  const provenance = useQuery({
    queryKey: ["page-category-provenance", String(detail.site_id), String(detail.page.resource_id)],
    queryFn: () => getPageCategoryProvenance(String(detail.site_id), String(detail.page.resource_id)),
  });
  const exclusion = useMutation({
    mutationFn: (item: { categoryId: number; excluded: boolean }) => item.excluded
      ? removePageCategoryExclusion(String(detail.site_id), String(detail.page.resource_id), item.categoryId)
      : addPageCategoryExclusion(String(detail.site_id), String(detail.page.resource_id), item.categoryId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["page-category-provenance", String(detail.site_id), String(detail.page.resource_id)] });
      await queryClient.invalidateQueries({ queryKey: ["site-page", String(detail.site_id), String(detail.page.resource_id)] });
    },
  });
  return (
    <div className="grid grid-cols-1 gap-5 xl:grid-cols-[minmax(0,1fr)_380px]">
      <section className="rounded-md border border-stone-200 bg-white p-4 shadow-sm">
        <h2 className="mb-4 text-base font-semibold">Latest observation</h2>
        <DefinitionList
          items={[
            {
              label: "Observation status",
              value: detail.page.latest_http_status ? (
                <StatusBadge
                  status={String(detail.page.latest_http_status)}
                  label={String(detail.page.latest_http_status)}
                />
              ) : detail.page.latest_fetch_state ? (
                formatStatus(detail.page.latest_fetch_state)
              ) : (
                "No retained observations"
              ),
            },
            {
              label: "Latest title",
              value: detail.page.latest_title ?? "Not available",
            },
            {
              label: "Latest retrieval",
              value: retrievalLabel(detail.page.latest_retrieval_method),
            },
            {
              label: "Latest parse",
              value: parseLabel(detail.page.latest_parse_method),
            },
            {
              label: "Latest error",
              value: detail.page.latest_error_type
                ? `${formatStatus(detail.page.latest_error_type)}: ${detail.page.latest_error_message ?? "No details"}`
                : "None",
            },
            {
              label: "Reused from observation",
              value: detail.page.latest_reused_from_snapshot_id
                ? String(detail.page.latest_reused_from_snapshot_id)
                : "Not reused",
            },
            {
              label: "First observed",
              value: detail.page.first_observed_at
                ? formatDate(detail.page.first_observed_at)
                : "No retained observations",
            },
            {
              label: "Latest observed",
              value: detail.page.latest_observed_at
                ? formatDate(detail.page.latest_observed_at)
                : "No retained observations",
            },
          ]}
        />
      </section>
      <section className="rounded-md border border-stone-200 bg-white p-4 shadow-sm">
        <div className="mb-4 flex items-center justify-between gap-2">
          <h2 className="text-base font-semibold">Organization</h2>
          <Button type="button" onClick={() => setEditing((value) => !value)}>
            {editing ? "Cancel" : "Edit organization"}
          </Button>
        </div>
        {editing ? (
          <OrganizationEditor detail={detail} close={() => setEditing(false)} />
        ) : (
          <DefinitionList
            items={[
              {
                label: "Workflow status",
                value: (
                  <WorkflowStatusBadge status={detail.page.workflow_status} />
                ),
              },
              {
                label: "Owner",
                value: detail.page.owner_label ?? "Unassigned",
              },
              {
                label: "Categories",
                value: (
                  <PageCategoryBadges categories={detail.page.categories} />
                ),
              },
              {
                label: "Category provenance",
                value: provenance.isLoading ? "Loading..." : provenance.data?.items.length ? (
                  <div className="space-y-2">{provenance.data.items.map((item) => <div key={item.category_id} className="text-sm"><div className="font-medium">{item.category_name}</div><div className="text-xs text-stone-500">{item.effective_reason}{item.matching_rules.length ? `: ${item.matching_rules.map((rule) => rule.name).join(", ")}` : ""}</div>{item.matching_rules.length || item.automatic_exclusion ? <button type="button" className="mt-1 text-xs underline" onClick={() => exclusion.mutate({ categoryId: item.category_id, excluded: item.automatic_exclusion })}>{item.automatic_exclusion ? "Allow automatic Category" : "Exclude automatic Category"}</button> : null}</div>)}</div>
                ) : "No Category support",
              },
              { label: "Notes", value: String(detail.page.note_count) },
              {
                label: "First associated with Site",
                value: formatDate(detail.page.associated_at),
              },
              {
                label: "Retained observations",
                value: String(detail.page.observation_count),
              },
            ]}
          />
        )}
      </section>
    </div>
  );
}

function OrganizationEditor({
  detail,
  close,
}: {
  detail: PersistentPageDetail;
  close: () => void;
}) {
  const queryClient = useQueryClient();
  const siteId = String(detail.site_id);
  const resourceId = String(detail.page.resource_id);
  const categories = useQuery({
    queryKey: ["page-categories", siteId],
    queryFn: () => listPageCategories(siteId, "?active_state=all&limit=200"),
  });
  const provenance = useQuery({
    queryKey: ["page-category-provenance", siteId, resourceId],
    queryFn: () => getPageCategoryProvenance(siteId, resourceId),
  });
  const [owner, setOwner] = useState(detail.page.owner_label ?? "");
  const [workflow, setWorkflow] = useState(detail.page.workflow_status);
  const [categoryIds, setCategoryIds] = useState<number[]>([]);
  useEffect(() => {
    if (provenance.data) setCategoryIds(provenance.data.items.filter((item) => item.manually_assigned).map((item) => item.category_id));
  }, [provenance.data]);
  const save = useMutation({
    mutationFn: () =>
      updatePageMetadata(siteId, resourceId, {
        owner_label: owner || null,
        workflow_status: workflow,
        category_ids: categoryIds,
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: ["site-page", siteId, resourceId],
      });
      await queryClient.invalidateQueries({ queryKey: ["site-pages", siteId] });
      await queryClient.invalidateQueries({ queryKey: ["page-category-provenance", siteId, resourceId] });
      close();
    },
  });
  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        save.mutate();
      }}
      className="space-y-3"
    >
      <label className="block text-sm font-medium">
        Owner
        <input
          value={owner}
          onChange={(event) => setOwner(event.target.value)}
          maxLength={128}
          className="mt-1 w-full rounded-md border border-stone-300 px-3 py-2"
        />
      </label>
      <label className="block text-sm font-medium">
        Workflow status
        <select
          value={workflow}
          onChange={(event) => setWorkflow(event.target.value)}
          className="mt-1 w-full rounded-md border border-stone-300 px-3 py-2"
        >
          {WORKFLOWS.map((item) => (
            <option key={item} value={item}>
              {formatStatus(item)}
            </option>
          ))}
        </select>
      </label>
      <fieldset>
        <legend className="text-sm font-medium">Categories</legend>
        <div className="mt-2 max-h-48 space-y-2 overflow-auto">
          {categories.data?.items
            .filter(
              (category) =>
                category.is_active || categoryIds.includes(category.id),
            )
            .map((category) => (
              <label
                key={category.id}
                className="flex items-center gap-2 text-sm"
              >
                <input
                  type="checkbox"
                  checked={categoryIds.includes(category.id)}
                  onChange={(event) =>
                    setCategoryIds((current) =>
                      event.target.checked
                        ? [...current, category.id]
                        : current.filter((id) => id !== category.id),
                    )
                  }
                />
                {category.name}{provenance.data?.items.some((item) => item.category_id === category.id && item.matching_rules.length) ? " (also assigned by Rule)" : ""}
                {!category.is_active ? " (Archived)" : ""}
              </label>
            ))}
        </div>
      </fieldset>
      {save.error || categories.error ? (
        <ErrorBanner
          error={save.error ?? categories.error}
          title="Could not update organization"
        />
      ) : null}
      <Button type="submit" loading={save.isPending} disabled={provenance.isLoading}>
        Save organization
      </Button>
    </form>
  );
}

function ScansTab({
  siteId,
  resourceId,
}: {
  siteId: string;
  resourceId: string;
}) {
  const [searchParams, setSearchParams] = useSearchParams();
  const pagination = useUrlPagination({ prefix: "page_scans" });
  const query = new URLSearchParams();
  for (const key of [
    "scope",
    "scan_status",
    "fetch_state",
    "error_state",
    "retrieval_method",
    "parse_method",
    "direction",
  ]) {
    const value = searchParams.get(key);
    if (value) query.set(key, value);
  }
  query.set("limit", String(pagination.limit));
  query.set("offset", String(pagination.offset));
  const observations = useQuery({
    queryKey: ["site-page-observations", siteId, resourceId, query.toString()],
    queryFn: () =>
      listPageObservations(siteId, resourceId, `?${query.toString()}`),
  });
  useEffect(() => pagination.ensureValid(observations.data?.total), [observations.data?.total, pagination]);
  const controls = observations.data ? <PaginatedTableControls total={observations.data.total} limit={pagination.limit} offset={pagination.offset} onPageChange={pagination.setPage} onPageSizeChange={pagination.setPageSize} itemLabel="Scan appearance" isLoading={observations.isFetching && !observations.isLoading} /> : null;
  return (
    <section className="rounded-md border border-stone-200 bg-white p-4 shadow-sm">
      <div className="mb-4 flex flex-wrap gap-3">
        <select
          aria-label="Scan scope"
          value={searchParams.get("scope") ?? "site"}
          onChange={(event) =>
            setScanParam(setSearchParams, "scope", event.target.value)
          }
          className="rounded-md border border-stone-300 px-3 py-2 text-sm"
        >
          <option value="site">This Site</option>
          <option value="all">All Sites</option>
        </select>
        <select
          aria-label="Observation error filter"
          value={searchParams.get("error_state") ?? "any"}
          onChange={(event) =>
            setScanParam(setSearchParams, "error_state", event.target.value)
          }
          className="rounded-md border border-stone-300 px-3 py-2 text-sm"
        >
          <option value="any">All observations</option>
          <option value="with_errors">Observation failed</option>
          <option value="without_errors">Without crawler errors</option>
        </select>
      </div>
      {observations.error ? (
        <ErrorBanner error={observations.error} title="Could not load Scans" />
      ) : null}
      {observations.isLoading ? (
        <LoadingBlock label="Loading Scans..." />
      ) : null}
      {controls ? <div className="mb-4">{controls}</div> : null}
      {observations.data?.items.length ? (
        <ObservationTable observations={observations.data.items} />
      ) : !observations.isLoading ? (
        <EmptyState
          title="No Scan appearances"
          message="No retained observations match these filters."
        />
      ) : null}
      {controls ? <div className="mt-4">{controls}</div> : null}
    </section>
  );
}

function ObservationTable({
  observations,
}: {
  observations: PageObservation[];
}) {
  const values = { scan: (item: PageObservation) => item.scan_id, observation: (item: PageObservation) => item.snapshot_id, status: (item: PageObservation) => item.http_status ?? item.fetch_state, retrieval: (item: PageObservation) => item.retrieval_method, response: (item: PageObservation) => item.response_time_ms ?? item.crawl_depth, rendered: (item: PageObservation) => item.rendered_capture_state };
  const { sortedItems, sort, changeSort } = useTableSort(observations, values);
  return (
    <div className="overflow-x-auto">
      <table className="min-w-full text-left text-sm">
        <thead className="bg-stone-100 text-xs uppercase text-stone-500">
          <tr>
            {[["scan", "Scan"], ["observation", "Observation"], ["status", "Status"], ["retrieval", "Retrieval"], ["response", "Depth / response"], ["rendered", "Rendered"]].map(([column, label]) => <SortableTableHeader key={column} column={column} label={label} activeColumn={sort?.column ?? null} direction={sort?.direction ?? null} onChange={changeSort} />)}
            <th className="px-3 py-2 font-medium">Actions</th>
          </tr>
        </thead>
        <tbody>
          {sortedItems.map((item) => (
            <tr
              key={item.snapshot_id}
              className="border-t border-stone-100 align-top"
            >
              <td className="px-3 py-2">
                <span className="block font-medium">Scan {item.scan_id}</span>
                <span className="text-xs text-stone-500">
                  {formatStatus(item.scan_status)} -{" "}
                  {formatDate(item.scan_created_at)}
                </span>
              </td>
              <td className="px-3 py-2">
                <span className="block">Observation {item.snapshot_id}</span>
                <span className="text-xs text-stone-500">
                  {formatDate(item.observed_at)}
                </span>
              </td>
              <td className="px-3 py-2">
                {item.http_status ? (
                  <StatusBadge
                    status={String(item.http_status)}
                    label={String(item.http_status)}
                  />
                ) : (
                  <StatusBadge
                    status={item.fetch_state}
                    label={
                      item.error_type
                        ? `Observation failed: ${formatStatus(item.error_type)}`
                        : formatStatus(item.fetch_state)
                    }
                  />
                )}
              </td>
              <td className="px-3 py-2">
                <span className="block">
                  {retrievalLabel(item.retrieval_method)}
                </span>
                <span className="text-xs text-stone-500">
                  {parseLabel(item.parse_method)}
                </span>
                {item.reused_from_snapshot_id ? (
                  <span className="block text-xs text-stone-500">
                    from snapshot {item.reused_from_snapshot_id}
                  </span>
                ) : null}
              </td>
              <td className="px-3 py-2">
                Depth {item.crawl_depth}
                <span className="block text-xs text-stone-500">
                  {item.response_time_ms != null
                    ? `${item.response_time_ms} ms`
                    : "No response time"}
                </span>
              </td>
              <td className="px-3 py-2">{item.rendered_capture_state ? <StatusBadge status={item.rendered_capture_state} /> : "Not attempted"}</td>
              <td className="px-3 py-2 text-xs">
                <Link className="block underline" to={`/scans/${item.scan_id}`}>
                  Open Scan
                </Link>
                <Link
                  className="block underline"
                  to={`/scans/${item.scan_id}/pages/${item.snapshot_id}`}
                >
                  Open Observation
                </Link>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function BrowserEvidenceTab({ siteId, resourceId }: { siteId: string; resourceId: string }) {
  const observations = useQuery({
    queryKey: ["site-page-browser-observations", siteId, resourceId],
    queryFn: () => listPageObservations(siteId, resourceId, "?scope=site&limit=200"),
  });
  if (observations.isLoading) return <LoadingBlock label="Loading browser evidence..." />;
  if (observations.error) return <ErrorBanner error={observations.error} title="Could not load browser evidence" />;
  const rendered = observations.data?.items.filter((item) => item.rendered_capture_state) ?? [];
  if (!rendered.length) return <EmptyState title="No browser evidence" message="No retained Scan attempted a browser-rendered observation for this Page." />;
  return <section className="rounded-md border border-stone-200 bg-white p-4 shadow-sm"><h2 className="mb-4 text-base font-semibold">Browser evidence history</h2><ObservationTable observations={rendered} /></section>;
}

function LinksTab({ detail }: { detail: PersistentPageDetail }) {
  const [searchParams, setSearchParams] = useSearchParams();
  const direction = searchParams.get("link_direction") ?? "outgoing";
  const snapshotId =
    searchParams.get("link_snapshot") ??
    (detail.page.latest_snapshot_id
      ? String(detail.page.latest_snapshot_id)
      : "");
  const role = searchParams.get("link_role") ?? "all";
  const pagination = useUrlPagination({ prefix: direction === "outgoing" ? "outgoing" : "inbound" });
  const observations = useQuery({
    queryKey: [
      "site-page-link-observations",
      detail.site_id,
      detail.page.resource_id,
    ],
    queryFn: () =>
      listPageObservations(
        String(detail.site_id),
        String(detail.page.resource_id),
        "?scope=site&limit=200",
      ),
  });
  const outgoing = useQuery({
    queryKey: ["outgoing-links", snapshotId, role, pagination.limit, pagination.offset],
    queryFn: () =>
      getOutgoingLinks(
        snapshotId,
        `?limit=${pagination.limit}&offset=${pagination.offset}${
          role === "all" ? "" : `&link_role=${encodeURIComponent(role)}`
        }`,
      ),
    enabled: Boolean(snapshotId) && direction === "outgoing",
  });
  const inbound = useQuery({
    queryKey: ["inbound-links", snapshotId, role, pagination.limit, pagination.offset],
    queryFn: () =>
      getInboundLinks(
        snapshotId,
        `?limit=${pagination.limit}&offset=${pagination.offset}${
          role === "all" ? "" : `&link_role=${encodeURIComponent(role)}`
        }`,
      ),
    enabled: Boolean(snapshotId) && direction === "inbound",
  });
  const activeData = direction === "outgoing" ? outgoing.data : inbound.data;
  useEffect(() => pagination.ensureValid(activeData?.total), [activeData?.total, pagination]);
  if (!snapshotId)
    return (
      <EmptyState
        title="No retained observations"
        message="Links require a retained Page observation."
      />
    );
  const links =
    direction === "outgoing"
      ? (outgoing.data?.items ?? [])
      : (inbound.data?.items ?? []);
  const filtered =
    role === "all" || direction === "inbound"
      ? links
      : links.filter(
          (link) => (link.link_role ?? "legacy_unclassified") === role,
        );
  const error = direction === "outgoing" ? outgoing.error : inbound.error;
  const loading =
    direction === "outgoing" ? outgoing.isLoading : inbound.isLoading;
  const controls = activeData ? <PaginatedTableControls total={activeData.total} limit={pagination.limit} offset={pagination.offset} onPageChange={pagination.setPage} onPageSizeChange={pagination.setPageSize} itemLabel="link occurrence" isLoading={(direction === "outgoing" ? outgoing.isFetching : inbound.isFetching) && !loading} /> : null;
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-3 rounded-md border border-stone-200 bg-white p-4 shadow-sm">
        <select
          aria-label="Link observation"
          value={snapshotId}
          onChange={(event) =>
            setLinkParam(setSearchParams, "link_snapshot", event.target.value)
          }
          className="max-w-md rounded-md border border-stone-300 px-3 py-2"
        >
          {(observations.data?.items ?? []).map((observation) => (
            <option
              key={observation.snapshot_id}
              value={observation.snapshot_id}
            >
              Scan {observation.scan_id} - {formatDate(observation.observed_at)}
            </option>
          ))}
        </select>
        <select
          aria-label="Link direction"
          value={direction}
          onChange={(event) =>
            setLinkParam(setSearchParams, "link_direction", event.target.value)
          }
          className="rounded-md border border-stone-300 px-3 py-2"
        >
          <option value="outgoing">Outgoing</option>
          <option value="inbound">Inbound</option>
        </select>
        <select
          aria-label="Link role"
          value={role}
          onChange={(event) =>
            setLinkParam(setSearchParams, "link_role", event.target.value)
          }
          className="rounded-md border border-stone-300 px-3 py-2"
        >
          <option value="all">All link roles</option>
          {[
            "navigation",
            "main_content",
            "footer",
            "sidebar",
            "breadcrumb",
            "header_utility",
            "download",
            "email",
            "telephone",
            "image",
            "unknown",
            "legacy_unclassified",
          ].map((item) => (
            <option key={item} value={item}>
              {formatStatus(item)}
            </option>
          ))}
        </select>
        <span className="self-center text-sm text-stone-600">
          Observation {snapshotId}
        </span>
      </div>
      {error ? (
        <ErrorBanner error={error} title="Could not load links" />
      ) : null}
      {loading ? <LoadingBlock label="Loading links..." /> : null}
      {controls}
      {!loading && !filtered.length ? (
        <EmptyState
          title="No links"
          message="No link occurrences match this observation and role."
        />
      ) : null}
      {filtered.length ? (
        <LinkTable links={filtered} inbound={direction === "inbound"} />
      ) : null}
      {controls}
    </div>
  );
}

function LinkTable({
  links,
  inbound,
}: {
  links: LinkOccurrence[];
  inbound: boolean;
}) {
  const values = { endpoint: (link: LinkOccurrence) => inbound && "source_requested_url" in link ? String(link.source_requested_url) : link.resolved_url ?? link.normalized_target_url, anchor: (link: LinkOccurrence) => link.anchor_text ?? link.aria_label, role: (link: LinkOccurrence) => link.link_role, scope: (link: LinkOccurrence) => link.scope_decision, evidence: (link: LinkOccurrence) => link.link_role_rule };
  const { sortedItems, sort, changeSort } = useTableSort(links, values);
  return (
    <div className="overflow-x-auto rounded-md border border-stone-200 bg-white shadow-sm">
      <table className="min-w-full text-left text-sm">
        <thead className="bg-stone-100 text-xs uppercase text-stone-500">
          <tr>
            {[["endpoint", inbound ? "Source" : "Destination"], ["anchor", "Anchor"], ["role", "Role"], ["scope", "Scope decision"], ["evidence", "Evidence"]].map(([column, label]) => <SortableTableHeader key={column} column={column} label={label} activeColumn={sort?.column ?? null} direction={sort?.direction ?? null} onChange={changeSort} />)}
          </tr>
        </thead>
        <tbody>
          {sortedItems.map((link) => (
            <tr key={link.id} className="border-t border-stone-100 align-top">
              <td className="max-w-md break-all px-3 py-2 font-mono text-xs">
                {inbound && "source_requested_url" in link
                  ? String(link.source_requested_url)
                  : (link.resolved_url ??
                    link.normalized_target_url ??
                    "Unavailable")}
              </td>
              <td className="px-3 py-2">
                {link.anchor_text ?? link.aria_label ?? "No visible text"}
              </td>
              <td className="px-3 py-2">
                <LinkRoleBadge
                  role={link.link_role}
                  label={link.link_role_label}
                  rule={link.link_role_rule}
                />
              </td>
              <td className="px-3 py-2">
                <StatusBadge
                  status={link.in_scope ? "completed" : "interrupted"}
                  label={formatStatus(link.scope_decision)}
                />
              </td>
              <td className="px-3 py-2 text-xs text-stone-600">
                {link.link_role_rule
                  ? formatStatus(link.link_role_rule)
                  : "Legacy occurrence"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function PageFrame({ children }: { children: React.ReactNode }) {
  return (
    <section className="mx-auto max-w-7xl px-4 py-6 sm:px-6 lg:px-8">
      {children}
    </section>
  );
}
function setTab(
  setSearchParams: ReturnType<typeof useSearchParams>[1],
  tab: string,
) {
  setSearchParams((current) => {
    const next = new URLSearchParams(current);
    next.set("tab", tab);
    return next;
  });
}
function setScanParam(
  setSearchParams: ReturnType<typeof useSearchParams>[1],
  key: string,
  value: string,
) {
  setSearchParams((current) => {
    const next = new URLSearchParams(current);
    next.set("tab", "scans");
    next.set(key, value);
    if (key !== "page_scans_offset") next.delete("page_scans_offset");
    return next;
  });
}
function setLinkParam(
  setSearchParams: ReturnType<typeof useSearchParams>[1],
  key: string,
  value: string,
) {
  setSearchParams((current) => {
    const next = new URLSearchParams(current);
    next.set("tab", "links");
    next.set(key, value);
    if (key !== "link_direction") {
      next.delete("outgoing_offset");
      next.delete("inbound_offset");
    }
    return next;
  });
}
function retrievalLabel(value: string | null) {
  const labels: Record<string, string> = {
    full_fetch: "Full download",
    full_fetch_after_revalidation_fallback: "Full download",
    conditional_not_modified: "Revalidated unchanged",
    non_html: "Non-HTML",
    failed: "Failed",
  };
  return value
    ? (labels[value] ?? formatStatus(value))
    : "No retained observations";
}
function parseLabel(value: string | null) {
  const labels: Record<string, string> = {
    parsed: "Full parse",
    reused_exact_hash: "Parsed result reused",
    reused_not_modified: "Parsed result reused",
    not_applicable: "No parse",
    failed: "Parse failed",
  };
  return value
    ? (labels[value] ?? formatStatus(value))
    : "No retained observations";
}
