import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FormEvent, useEffect, useState } from "react";
import {
  Link,
  useNavigate,
  useParams,
  useSearchParams,
} from "react-router-dom";

import {
  addManualUrls,
  bulkPageCategories,
  bulkPageMetadata,
  cancelSourceRefresh,
  createSource,
  createAiDocumentSource,
  createPageCategory,
  createSiteNote,
  deletePageCategory,
  getPageCategoryDeletionPreview,
  deleteSite,
  deleteSource,
  discoverRobots,
  discoverAiDocumentSources,
  getWorkerHealth,
  getSite,
  listInventory,
  listPageCategories,
  listSiteNotes,
  listJobs,
  listSitePages,
  listSources,
  refreshSource,
  updatePageCategory,
  updateSite,
} from "../api/client";
import { NotesPanel } from "../components/NotesPanel";
import { CategoryRuleHistoryPanel, CategoryRulesPanel } from "../components/CategoryRulesPanel";
import { ResourceInventoryView } from "../components/ResourceInventoryView";
import {
  PageCategoryBadges,
  WorkflowStatusBadge,
} from "../components/PageOrganization";
import { Button } from "../components/ui/Button";
import { DefinitionList } from "../components/ui/DefinitionList";
import { EmptyState } from "../components/ui/EmptyState";
import { ErrorBanner } from "../components/ui/ErrorBanner";
import { Field } from "../components/ui/Field";
import { LoadingBlock } from "../components/ui/Loading";
import { PaginatedTableControls } from "../components/ui/PaginatedTableControls";
import { StatusBadge } from "../components/ui/StatusBadge";
import { classificationLabel } from "../types/siteClassifications";
import type { Job, WorkerHealth } from "../types/jobs";
import type {
  InventoryItem,
  PageCategory,
  PersistentPage,
  Site,
  UrlSource,
} from "../types/scans";
import { defaultAiDocumentSettings } from "../types/aiDocuments";
import {
  formatDate,
  formatStatus,
  isTerminalStatus,
  plural,
} from "../utils/format";
import { useDocumentTitle } from "../utils/useDocumentTitle";
import { useUrlPagination } from "../utils/useUrlPagination";

export function SiteDetailPage() {
  const { siteId = "" } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  const tab = searchParams.get("tab") ?? "overview";
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const site = useQuery({
    queryKey: ["site", siteId],
    queryFn: () => getSite(siteId),
  });
  useDocumentTitle(site.data?.name ?? "Site");
  const toggleActive = useMutation({
    mutationFn: (next: boolean) => updateSite(siteId, { is_active: next }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["site", siteId] });
      await queryClient.invalidateQueries({ queryKey: ["sites"] });
    },
  });
  const remove = useMutation({
    mutationFn: () => deleteSite(siteId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["sites"] });
      navigate("/sites");
    },
  });

  if (site.isLoading)
    return (
      <PageFrame>
        <LoadingBlock label="Loading site..." />
      </PageFrame>
    );
  if (site.error)
    return (
      <PageFrame>
        <ErrorBanner error={site.error} title="Could not load site" />
      </PageFrame>
    );
  if (!site.data)
    return (
      <PageFrame>
        <EmptyState
          title="Site not found"
          message="The saved site may have been deleted."
        />
      </PageFrame>
    );

  return (
    <PageFrame>
      <div className="mb-5 flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0">
          <div className="mb-2 text-sm text-stone-500">
            <Link to="/sites" className="underline">
              Sites
            </Link>{" "}
            / {site.data.name}
          </div>
          <h1 className="truncate text-2xl font-semibold">{site.data.name}</h1>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <StatusBadge
              status={site.data.is_active ? "completed" : "interrupted"}
              label={site.data.is_active ? "Active" : "Inactive"}
            />
            <span className="font-mono text-xs text-stone-600">
              {site.data.base_url}
            </span>
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          {site.data.is_active ? (
            <Link
              className="rounded-md border border-neutral-900 bg-neutral-900 px-3 py-2 text-sm font-medium text-white"
              to={`/scans/new?site_id=${site.data.id}`}
            >
              Run scan
            </Link>
          ) : null}
          <Link
            className="rounded-md border border-stone-300 bg-white px-3 py-2 text-sm font-medium"
            to={`/sites/${site.data.id}/edit`}
          >
            Edit site
          </Link>
          <Button
            type="button"
            loading={toggleActive.isPending}
            onClick={() => toggleActive.mutate(!site.data!.is_active)}
          >
            {site.data.is_active ? "Disable" : "Reactivate"}
          </Button>
          {site.data.total_scan_count === 0 ? (
            <Button
              type="button"
              variant="danger"
              loading={remove.isPending}
              onClick={() => {
                if (
                  window.confirm(
                    `Delete ${site.data?.name}? This cannot be undone.`,
                  )
                )
                  remove.mutate();
              }}
            >
              Delete
            </Button>
          ) : null}
        </div>
      </div>
      {toggleActive.error || remove.error ? (
        <ErrorBanner
          error={toggleActive.error ?? remove.error}
          title="Site action failed"
        />
      ) : null}
      <div className="mb-5 flex gap-2 border-b border-stone-200 text-sm">
        {[
          "overview",
          "scans",
          "pages",
          "resources",
          "categories",
          "sources",
          "inventory",
          "notes",
        ].map((item) => (
          <button
            key={item}
            type="button"
            onClick={() => setTab(setSearchParams, item)}
            className={`border-b-2 px-3 py-2 capitalize ${tab === item ? "border-neutral-900 text-neutral-900" : "border-transparent text-stone-500"}`}
          >
            {item}
          </button>
        ))}
      </div>
      {tab === "overview" ? <OverviewTab site={site.data} /> : null}
      {tab === "scans" ? <ScansTab site={site.data} /> : null}
      {tab === "pages" ? <PagesTab site={site.data} /> : null}
      {tab === "resources" ? <div className="space-y-4"><p className="text-sm text-stone-600">Resources are non-HTML files and embedded references retained from Scans. URL Inventory remains the separate set of candidate Page URLs declared by Sources.</p><ResourceInventoryView scope="site" id={siteId} /></div> : null}
      {tab === "categories" ? <CategoriesTab site={site.data} /> : null}
      {tab === "sources" ? <SourcesTab site={site.data} /> : null}
      {tab === "inventory" ? <InventoryTab site={site.data} /> : null}
      {tab === "notes" ? (
        <NotesPanel
          queryKey={["site-notes", siteId]}
          list={(query) => listSiteNotes(siteId, query)}
          create={(body, pinned) => createSiteNote(siteId, body, pinned)}
          context={site.data.name}
        />
      ) : null}
    </PageFrame>
  );
}

function PagesTab({ site }: { site: Site }) {
  const [searchParams, setSearchParams] = useSearchParams();
  const pagination = useUrlPagination({ prefix: "site_pages" });
  const queryClient = useQueryClient();
  const [selected, setSelected] = useState<number[]>([]);
  const [bulkCategory, setBulkCategory] = useState("");
  const [bulkOwner, setBulkOwner] = useState("");
  const [bulkWorkflow, setBulkWorkflow] = useState("");
  const query = new URLSearchParams();
  for (const key of [
    "search",
    "host",
    "path_prefix",
    "category_id",
    "uncategorized",
    "workflow_status",
    "owner",
    "unassigned_owner",
    "has_notes",
    "sort",
    "direction",
  ]) {
    const value = searchParams.get(key);
    if (value) query.set(key, value);
  }
  query.set("limit", String(pagination.limit));
  query.set("offset", String(pagination.offset));
  const pages = useQuery({
    queryKey: ["site-pages", String(site.id), query.toString()],
    queryFn: () => listSitePages(String(site.id), `?${query.toString()}`),
  });
  const categories = useQuery({
    queryKey: ["page-categories", String(site.id)],
    queryFn: () =>
      listPageCategories(String(site.id), "?active_state=all&limit=200"),
  });
  useEffect(() => pagination.ensureValid(pages.data?.total), [pages.data?.total, pagination]);
  const controls = pages.data ? <PaginatedTableControls total={pages.data.total} limit={pagination.limit} offset={pagination.offset} onPageChange={pagination.setPage} onPageSizeChange={pagination.setPageSize} itemLabel="Page" isLoading={pages.isFetching && !pages.isLoading} /> : null;
  const bulk = useMutation({
    mutationFn: async (action: "add" | "remove" | "owner" | "workflow") => {
      if (action === "add" || action === "remove")
        return bulkPageCategories(String(site.id), {
          resource_ids: selected,
          add_category_ids: action === "add" ? [Number(bulkCategory)] : [],
          remove_category_ids:
            action === "remove" ? [Number(bulkCategory)] : [],
        });
      return bulkPageMetadata(String(site.id), {
        resource_ids: selected,
        ...(action === "owner"
          ? { owner_label: bulkOwner || null }
          : { workflow_status: bulkWorkflow }),
      });
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: ["site-pages", String(site.id)],
      });
      setSelected([]);
    },
  });
  return (
    <section className="rounded-md border border-stone-200 bg-white p-4 shadow-sm">
      <div className="mb-4 grid grid-cols-1 gap-3 md:grid-cols-3 xl:grid-cols-4">
        <input
          aria-label="Search site pages"
          value={searchParams.get("search") ?? ""}
          onChange={(event) =>
            setSearchParam(setSearchParams, "search", event.target.value)
          }
          placeholder="Search pages"
          className="rounded-md border border-stone-300 px-3 py-2 text-sm"
        />
        <input
          aria-label="Page host"
          value={searchParams.get("host") ?? ""}
          onChange={(event) =>
            setSearchParam(setSearchParams, "host", event.target.value)
          }
          placeholder="Host"
          className="rounded-md border border-stone-300 px-3 py-2 text-sm"
        />
        <input
          aria-label="Page path prefix"
          value={searchParams.get("path_prefix") ?? ""}
          onChange={(event) =>
            setSearchParam(setSearchParams, "path_prefix", event.target.value)
          }
          placeholder="Path prefix"
          className="rounded-md border border-stone-300 px-3 py-2 text-sm"
        />
        <select
          aria-label="Workflow status filter"
          value={searchParams.get("workflow_status") ?? ""}
          onChange={(event) => {
            setSelected([]);
            setSearchParam(
              setSearchParams,
              "workflow_status",
              event.target.value,
            );
          }}
          className="rounded-md border border-stone-300 px-3 py-2 text-sm"
        >
          <option value="">All workflow statuses</option>
          {[
            "unreviewed",
            "needs_review",
            "approved",
            "updating",
            "deprecated",
            "archived",
          ].map((item) => (
            <option key={item} value={item}>
              {formatStatus(item)}
            </option>
          ))}
        </select>
        <select
          aria-label="Category filter"
          value={searchParams.get("category_id") ?? ""}
          onChange={(event) => {
            setSelected([]);
            setSearchParam(setSearchParams, "category_id", event.target.value);
          }}
          className="rounded-md border border-stone-300 px-3 py-2 text-sm"
        >
          <option value="">All categories</option>
          {categories.data?.items.map((category) => (
            <option key={category.id} value={category.id}>
              {category.name}
            </option>
          ))}
        </select>
        <input
          aria-label="Owner filter"
          value={searchParams.get("owner") ?? ""}
          onChange={(event) => {
            setSelected([]);
            setSearchParam(setSearchParams, "owner", event.target.value);
          }}
          placeholder="Owner"
          className="rounded-md border border-stone-300 px-3 py-2 text-sm"
        />
      </div>
      {selected.length ? (
        <div className="mb-4 flex flex-wrap items-center gap-2 border-y border-stone-200 py-3">
          <strong className="text-sm">
            {selected.length} selected on this page
          </strong>
          <select
            aria-label="Bulk category"
            value={bulkCategory}
            onChange={(event) => setBulkCategory(event.target.value)}
            className="rounded-md border border-stone-300 px-2 py-1 text-sm"
          >
            <option value="">Choose category</option>
            {categories.data?.items.map((category) => (
              <option key={category.id} value={category.id}>
                {category.name}
              </option>
            ))}
          </select>
          <Button
            type="button"
            disabled={!bulkCategory}
            onClick={() => bulk.mutate("add")}
          >
            Add category
          </Button>
          <Button
            type="button"
            disabled={!bulkCategory}
            onClick={() => bulk.mutate("remove")}
          >
            Remove category
          </Button>
          <input
            aria-label="Bulk owner"
            value={bulkOwner}
            onChange={(event) => setBulkOwner(event.target.value)}
            placeholder="Owner or blank"
            className="rounded-md border border-stone-300 px-2 py-1 text-sm"
          />
          <Button type="button" onClick={() => bulk.mutate("owner")}>
            Set owner
          </Button>
          <select
            aria-label="Bulk workflow status"
            value={bulkWorkflow}
            onChange={(event) => setBulkWorkflow(event.target.value)}
            className="rounded-md border border-stone-300 px-2 py-1 text-sm"
          >
            <option value="">Choose workflow</option>
            {[
              "unreviewed",
              "needs_review",
              "approved",
              "updating",
              "deprecated",
              "archived",
            ].map((item) => (
              <option key={item} value={item}>
                {formatStatus(item)}
              </option>
            ))}
          </select>
          <Button
            type="button"
            disabled={!bulkWorkflow}
            onClick={() => bulk.mutate("workflow")}
          >
            Set workflow
          </Button>
        </div>
      ) : null}
      {bulk.error ? (
        <ErrorBanner error={bulk.error} title="Bulk update failed" />
      ) : null}
      {pages.error ? (
        <ErrorBanner error={pages.error} title="Could not load pages" />
      ) : null}
      {pages.isLoading ? <LoadingBlock label="Loading pages..." /> : null}
      {controls ? <div className="mb-4">{controls}</div> : null}
      {pages.data?.items.length ? (
        <SitePagesTable
          siteId={site.id}
          pages={pages.data.items}
          selected={selected}
          setSelected={setSelected}
        />
      ) : !pages.isLoading ? (
        <EmptyState
          title="No Site Pages"
          message="Run a scan for this Site to associate observed Pages."
        />
      ) : null}
      {controls ? <div className="mt-4">{controls}</div> : null}
    </section>
  );
}

function SitePagesTable({
  siteId,
  pages,
  selected,
  setSelected,
}: {
  siteId: number;
  pages: PersistentPage[];
  selected: number[];
  setSelected: (ids: number[]) => void;
}) {
  const allSelected =
    pages.length > 0 &&
    pages.every((page) => selected.includes(page.resource_id));
  return (
    <div className="overflow-x-auto">
      <table className="min-w-full text-left text-sm">
        <thead className="bg-stone-100 text-xs uppercase text-stone-500">
          <tr>
            <th className="px-3 py-2">
              <input
                aria-label="Select all Pages on this loaded page"
                type="checkbox"
                checked={allSelected}
                onChange={(event) =>
                  setSelected(
                    event.target.checked
                      ? pages.map((page) => page.resource_id)
                      : [],
                  )
                }
              />
            </th>
            {[
              "Page",
              "Owner",
              "Workflow",
              "Categories",
              "Notes",
              "Observations",
              "Latest observation",
              "Actions",
            ].map((header) => (
              <th key={header} scope="col" className="px-3 py-2">
                {header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {pages.map((page) => (
            <tr
              key={page.resource_id}
              className="border-t border-stone-100 align-top"
            >
              <td className="px-3 py-2">
                <input
                  aria-label={`Select ${page.normalized_url}`}
                  type="checkbox"
                  checked={selected.includes(page.resource_id)}
                  onChange={(event) =>
                    setSelected(
                      event.target.checked
                        ? [...selected, page.resource_id]
                        : selected.filter((id) => id !== page.resource_id),
                    )
                  }
                />
              </td>
              <td className="max-w-xl px-3 py-2">
                <Link
                  to={`/sites/${siteId}/pages/${page.resource_id}`}
                  className="block truncate font-mono text-xs underline"
                >
                  {page.normalized_url}
                </Link>
                <span className="mt-1 block text-xs text-stone-500">
                  {page.latest_title ?? "Untitled"}
                </span>
              </td>
              <td className="px-3 py-2">{page.owner_label ?? "Unassigned"}</td>
              <td className="px-3 py-2">
                <WorkflowStatusBadge status={page.workflow_status} />
              </td>
              <td className="px-3 py-2">
                <PageCategoryBadges categories={page.categories} />
              </td>
              <td className="px-3 py-2">{page.note_count}</td>
              <td className="px-3 py-2">
                {plural(page.observation_count, "Scan")}
              </td>
              <td className="px-3 py-2">
                {page.latest_http_status ? (
                  <StatusBadge
                    status={String(page.latest_http_status)}
                    label={String(page.latest_http_status)}
                  />
                ) : (
                  "Not available"
                )}
                <span className="mt-1 block text-xs text-stone-500">
                  {formatDate(page.latest_observed_at)}
                </span>
              </td>
              <td className="px-3 py-2">
                <div className="flex flex-col gap-1 text-xs">
                  <Link
                    className="underline"
                    to={`/sites/${siteId}/pages/${page.resource_id}`}
                  >
                    Open Page
                  </Link>
                  {page.latest_scan_id && page.latest_snapshot_id ? (
                    <Link
                      className="underline"
                      to={`/scans/${page.latest_scan_id}/pages/${page.latest_snapshot_id}`}
                    >
                      Latest observation
                    </Link>
                  ) : null}
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function CategoriesTab({ site }: { site: Site }) {
  const [view, setView] = useState<"categories" | "rules" | "history">("categories");
  const categories = useQuery({
    queryKey: ["page-categories", String(site.id)],
    queryFn: () => listPageCategories(String(site.id), "?active_state=all&limit=200"),
  });
  return <div className="space-y-4"><div className="flex gap-1 border-b border-stone-200" role="tablist">{(["categories", "rules", "history"] as const).map((item) => <button key={item} type="button" role="tab" aria-selected={view === item} onClick={() => setView(item)} className={`border-b-2 px-3 py-2 text-sm font-medium ${view === item ? "border-stone-900 text-stone-900" : "border-transparent text-stone-500"}`}>{item === "history" ? "Evaluation History" : formatStatus(item)}</button>)}</div>{view === "categories" ? <CategoryListPanel site={site} /> : null}{view === "rules" ? categories.isLoading ? <LoadingBlock label="Loading categories..." /> : categories.error ? <ErrorBanner error={categories.error} title="Could not load categories" /> : <CategoryRulesPanel siteId={String(site.id)} categories={categories.data?.items ?? []} timeZone={site.display_timezone} /> : null}{view === "history" ? <CategoryRuleHistoryPanel siteId={String(site.id)} timeZone={site.display_timezone} /> : null}</div>;
}

function CategoryListPanel({ site }: { site: Site }) {
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [color, setColor] = useState("stone");
  const categories = useQuery({
    queryKey: ["page-categories", String(site.id)],
    queryFn: () =>
      listPageCategories(String(site.id), "?active_state=all&limit=200"),
  });
  const refresh = () =>
    queryClient.invalidateQueries({
      queryKey: ["page-categories", String(site.id)],
    });
  const create = useMutation({
    mutationFn: () =>
      createPageCategory(String(site.id), { name, color_key: color }),
    onSuccess: async () => {
      setName("");
      await refresh();
    },
  });
  return (
    <div className="space-y-4">
      <form
        onSubmit={(event) => {
          event.preventDefault();
          if (name.trim()) create.mutate();
        }}
        className="rounded-md border border-stone-200 bg-white p-4 shadow-sm"
      >
        <h2 className="mb-3 text-base font-semibold">Create category</h2>
        <div className="flex flex-wrap gap-3">
          <label className="flex-1 text-sm font-medium">
            Name
            <input
              value={name}
              onChange={(event) => setName(event.target.value)}
              maxLength={100}
              className="mt-1 w-full rounded-md border border-stone-300 px-3 py-2"
            />
          </label>
          <label className="text-sm font-medium">
            Color
            <select
              value={color}
              onChange={(event) => setColor(event.target.value)}
              className="mt-1 block rounded-md border border-stone-300 px-3 py-2"
            >
              {[
                "stone",
                "red",
                "orange",
                "amber",
                "green",
                "teal",
                "blue",
                "indigo",
                "violet",
                "pink",
              ].map((item) => (
                <option key={item} value={item}>
                  {formatStatus(item)}
                </option>
              ))}
            </select>
          </label>
          <Button
            type="submit"
            loading={create.isPending}
            disabled={!name.trim()}
          >
            Create category
          </Button>
        </div>
      </form>
      {categories.error || create.error ? (
        <ErrorBanner
          error={categories.error ?? create.error}
          title="Category action failed"
        />
      ) : null}
      {categories.isLoading ? (
        <LoadingBlock label="Loading categories..." />
      ) : null}
      {categories.data?.items.length ? (
        <div className="space-y-3">
          {categories.data.items.map((category) => (
            <CategoryRow
              key={category.id}
              siteId={String(site.id)}
              category={category}
              refresh={refresh}
            />
          ))}
        </div>
      ) : !categories.isLoading ? (
        <EmptyState
          title="No categories"
          message="Create a flat category to organize this Site's Pages."
        />
      ) : null}
    </div>
  );
}

function CategoryRow({
  siteId,
  category,
  refresh,
}: {
  siteId: string;
  category: PageCategory;
  refresh: () => Promise<unknown>;
}) {
  const [name, setName] = useState(category.name);
  const [description, setDescription] = useState(category.description ?? "");
  const save = useMutation({
    mutationFn: () =>
      updatePageCategory(siteId, category.id, {
        name,
        description: description || null,
      }),
    onSuccess: refresh,
  });
  const archive = useMutation({
    mutationFn: () =>
      updatePageCategory(siteId, category.id, {
        is_active: !category.is_active,
      }),
    onSuccess: refresh,
  });
  const remove = useMutation({
    mutationFn: async () => {
      const preview = await getPageCategoryDeletionPreview(siteId, category.id);
      const confirmed = window.confirm(
        `Delete ${category.name}? This removes ${preview.assignment_count} effective assignments, ${preview.manual_support_count} manual supports, ${preview.rule_support_count} Rule supports, ${preview.rule_count} Rules, and ${preview.exclusion_count} exclusions. Pages, Scans, notes, and projections are retained.`,
      );
      if (!confirmed) throw new Error("Deletion cancelled");
      return deletePageCategory(siteId, category.id);
    },
    onSuccess: refresh,
  });
  return (
    <section className="rounded-md border border-stone-200 bg-white p-4 shadow-sm">
      <form
        onSubmit={(event) => {
          event.preventDefault();
          save.mutate();
        }}
        className="grid gap-3 md:grid-cols-[minmax(180px,1fr)_minmax(240px,2fr)_auto]"
      >
        <label className="text-sm font-medium">
          Name
          <input
            value={name}
            onChange={(event) => setName(event.target.value)}
            className="mt-1 w-full rounded-md border border-stone-300 px-3 py-2"
          />
        </label>
        <label className="text-sm font-medium">
          Description
          <input
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            className="mt-1 w-full rounded-md border border-stone-300 px-3 py-2"
          />
        </label>
        <div className="flex flex-wrap items-end gap-2">
          <span className="self-center text-sm">
            {plural(category.assignment_count, "assignment")} ({category.manual_assignment_count} manual, {category.automatic_assignment_count} automatic, {plural(category.rule_count, "Rule")}, {plural(category.exclusion_count, "exclusion")})
          </span>
          <Button type="submit" loading={save.isPending}>
            Save
          </Button>
          <Button type="button" onClick={() => archive.mutate()}>
            {category.is_active ? "Archive" : "Reactivate"}
          </Button>
          <Button
            type="button"
            variant="danger"
            onClick={() => remove.mutate()}
          >
            Delete
          </Button>
        </div>
      </form>
      {save.error || archive.error || (remove.error && remove.error.message !== "Deletion cancelled") ? (
        <ErrorBanner
          error={save.error ?? archive.error ?? remove.error}
          title="Category action failed"
        />
      ) : null}
    </section>
  );
}

function PageFrame({ children }: { children: React.ReactNode }) {
  return (
    <section className="mx-auto max-w-7xl px-4 py-6 sm:px-6 lg:px-8">
      {children}
    </section>
  );
}

function OverviewTab({ site }: { site: Site }) {
  return (
    <div className="grid grid-cols-1 gap-5 xl:grid-cols-[minmax(0,1fr)_360px]">
      <div className="space-y-5">
        <section className="rounded-md border border-stone-200 bg-white p-4 shadow-sm">
          <h2 className="mb-4 text-base font-semibold">Site details</h2>
          <DefinitionList
            items={[
              {
                label: "Base URL",
                value: site.base_url,
                copyValue: site.base_url,
              },
              {
                label: "Description",
                value: site.description ?? "Not provided",
              },
              { label: "Group", value: classificationLabel(site.group_key) },
              { label: "Locale", value: site.locale ?? "Not specified" },
              {
                label: "Platform",
                value: classificationLabel(site.platform_key),
              },
              {
                label: "Ownership",
                value: classificationLabel(site.ownership_key),
              },
              { label: "Created", value: formatDate(site.created_at, { timeZone: site.display_timezone, showTimeZone: true }) },
              { label: "Updated", value: formatDate(site.updated_at, { timeZone: site.display_timezone, showTimeZone: true }) },
            ]}
          />
        </section>
        <section className="rounded-md border border-stone-200 bg-white p-4 shadow-sm">
          <h2 className="mb-3 text-base font-semibold">Saved scope</h2>
          <ScopeSummary site={site} />
          <details className="mt-4">
            <summary className="cursor-pointer text-sm font-medium">
              View saved scope JSON
            </summary>
            <pre className="mt-3 max-h-80 overflow-auto rounded-md border border-stone-200 bg-stone-50 p-3 text-xs">
              {JSON.stringify(site.scope_config, null, 2)}
            </pre>
          </details>
        </section>
      </div>
      <ScansTab site={site} compact />
    </div>
  );
}

function ScansTab({
  site,
  compact = false,
}: {
  site: Site;
  compact?: boolean;
}) {
  return (
    <section className="rounded-md border border-stone-200 bg-white p-4 shadow-sm">
      <h2 className="mb-3 text-base font-semibold">Recent scans</h2>
      <div className="mb-3 text-sm text-stone-600">
        {plural(site.total_scan_count, "scan")}
      </div>
      {site.recent_scans.length ? (
        <div
          className={
            compact ? "space-y-2" : "grid grid-cols-1 gap-2 md:grid-cols-2"
          }
        >
          {site.recent_scans.map((scan) => (
            <div
              key={scan.id}
              className="rounded-md border border-stone-200 px-3 py-2 text-sm"
            >
              <Link
                to={`/scans/${scan.id}`}
                className="block hover:bg-stone-50"
              >
                <StatusBadge status={scan.status} />
                <span className="mt-1 block text-xs text-stone-500">
                  {formatDate(scan.created_at, { timeZone: site.display_timezone, showTimeZone: true })} - {scan.discovered_count}{" "}
                  discovered - {scan.failed_count} failed
                </span>
              </Link>
              <Link
                to={`/scans/${scan.id}?tab=graph`}
                className="mt-2 inline-block text-xs font-medium underline"
              >
                View graph
              </Link>
            </div>
          ))}
        </div>
      ) : (
        <EmptyState
          title="No scans yet"
          message="Run a scan from this site to build history."
        />
      )}
    </section>
  );
}

function SourcesTab({ site }: { site: Site }) {
  const queryClient = useQueryClient();
  const [sitemapUrl, setSitemapUrl] = useState("");
  const [manualUrls, setManualUrls] = useState("");
  const [aiSourceUrl, setAiSourceUrl] = useState("");
  const [selectedAiCandidates, setSelectedAiCandidates] = useState<string[]>([]);
  const sources = useQuery({
    queryKey: ["sources", String(site.id)],
    queryFn: () => listSources(String(site.id), "?active_state=all&limit=100"),
  });
  const sourceJobs = useQuery({
    queryKey: ["jobs", "site-sources", String(site.id)],
    queryFn: () =>
      listJobs(
        `?website_property_id=${site.id}&job_type=source_refresh&limit=50`,
      ),
    refetchInterval: (query) =>
      query.state.data?.items.some((job) => !isTerminalStatus(job.status))
        ? 1500
        : false,
    placeholderData: (previous) => previous,
  });
  const workerHealth = useQuery({
    queryKey: ["worker-health"],
    queryFn: getWorkerHealth,
    enabled: Boolean(
      sourceJobs.data?.items.some((job) => !isTerminalStatus(job.status)),
    ),
    refetchInterval: 5000,
    placeholderData: (previous) => previous,
  });
  const addSitemap = useMutation({
    mutationFn: () =>
      createSource(String(site.id), {
        source_type: "sitemap",
        name: sitemapUrl,
        source_url: sitemapUrl,
        is_active: true,
        discovery_mode: "configured",
        settings_json: {},
      }),
    onSuccess: async () => {
      setSitemapUrl("");
      await queryClient.invalidateQueries({
        queryKey: ["sources", String(site.id)],
      });
    },
  });
  const refresh = useMutation({
    mutationFn: (source: UrlSource) =>
      refreshSource(String(site.id), String(source.id)),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: ["sources", String(site.id)],
      });
      await queryClient.invalidateQueries({
        queryKey: ["inventory", String(site.id)],
      });
      await queryClient.invalidateQueries({
        queryKey: ["jobs", "site-sources", String(site.id)],
      });
    },
  });
  const robots = useMutation({
    mutationFn: () => discoverRobots(String(site.id)),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: ["sources", String(site.id)],
      });
      await queryClient.invalidateQueries({
        queryKey: ["jobs", "site-sources", String(site.id)],
      });
    },
  });
  const aiDiscovery = useMutation({
    mutationFn: () => discoverAiDocumentSources(String(site.id)),
    onSuccess: (result) =>
      setSelectedAiCandidates(
        result.candidates
          .filter((candidate) => candidate.status === "found" && !candidate.already_configured)
          .map((candidate) => candidate.url),
      ),
  });
  const addAiSources = useMutation({
    mutationFn: async (urls: string[]) =>
      Promise.all(
        urls.map((url) =>
          createAiDocumentSource(String(site.id), {
            entry_url: url,
            name: new URL(url).pathname.split("/").filter(Boolean).join(" / ") || "AI documents",
            discovery_mode:
              aiDiscovery.data?.candidates.find((candidate) => candidate.url === url)
                ?.discovery_method ?? "configured",
            settings: defaultAiDocumentSettings(),
          }),
        ),
      ),
    onSuccess: async () => {
      setAiSourceUrl("");
      setSelectedAiCandidates([]);
      await queryClient.invalidateQueries({ queryKey: ["sources", String(site.id)] });
    },
  });
  const cancelRefresh = useMutation({
    mutationFn: (job: Job) =>
      cancelSourceRefresh(String(job.source_refresh_id)),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: ["sources", String(site.id)],
      });
      await queryClient.invalidateQueries({
        queryKey: ["jobs", "site-sources", String(site.id)],
      });
    },
  });
  const manual = useMutation({
    mutationFn: () => addManualUrls(String(site.id), manualUrls),
    onSuccess: async () => {
      setManualUrls("");
      await queryClient.invalidateQueries({
        queryKey: ["sources", String(site.id)],
      });
      await queryClient.invalidateQueries({
        queryKey: ["inventory", String(site.id)],
      });
    },
  });
  const remove = useMutation({
    mutationFn: (source: UrlSource) =>
      deleteSource(String(site.id), String(source.id)),
    onSuccess: async () =>
      queryClient.invalidateQueries({ queryKey: ["sources", String(site.id)] }),
  });

  function submitSitemap(event: FormEvent) {
    event.preventDefault();
    if (sitemapUrl.trim()) addSitemap.mutate();
  }

  return (
    <div className="space-y-5">
      {addSitemap.error ||
      refresh.error ||
      robots.error ||
      manual.error ||
      remove.error ||
      cancelRefresh.error ? (
        <ErrorBanner
          error={
            addSitemap.error ??
            refresh.error ??
            robots.error ??
            manual.error ??
            remove.error ??
            cancelRefresh.error
          }
          title="Source request failed"
        />
      ) : null}
      <section className="rounded-md border border-stone-200 bg-white p-4 shadow-sm">
        <div className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
          <div><h2 className="text-base font-semibold">AI Document Sources</h2><p className="mt-1 text-sm text-stone-600">Discover conventional llms.txt entry points and advertised nested indexes, or add a scoped URL directly.</p></div>
          <Button type="button" loading={aiDiscovery.isPending} onClick={() => aiDiscovery.mutate()}>Discover AI Document Sources</Button>
        </div>
        {aiDiscovery.data ? <div className="mt-4 rounded-md border border-stone-200"><div className="border-b border-stone-200 px-3 py-2 text-sm font-medium">Discovery candidates</div>{aiDiscovery.data.candidates.map((candidate) => <label key={`${candidate.discovery_method}-${candidate.url}`} className="flex items-start gap-3 border-b border-stone-100 px-3 py-3 last:border-0"><input type="checkbox" className="mt-1" disabled={candidate.status !== "found" || candidate.already_configured} checked={selectedAiCandidates.includes(candidate.url)} onChange={(event) => setSelectedAiCandidates((current) => event.target.checked ? [...current, candidate.url] : current.filter((url) => url !== candidate.url))} /><span className="min-w-0"><span className="block break-all font-mono text-xs">{candidate.url}</span><span className="mt-1 block text-xs text-stone-500">{formatStatus(candidate.discovery_method)} - {formatStatus(candidate.status)}{candidate.already_configured ? " - already configured" : ""}</span></span></label>)}<div className="p-3"><Button type="button" loading={addAiSources.isPending} disabled={!selectedAiCandidates.length} onClick={() => addAiSources.mutate(selectedAiCandidates)}>Add selected Sources</Button></div></div> : null}
        <div className="mt-4 flex flex-col gap-2 sm:flex-row"><input aria-label="AI Document Source URL" value={aiSourceUrl} onChange={(event) => setAiSourceUrl(event.target.value)} placeholder="https://www.example.com/docs/llms.txt" className="min-w-0 flex-1 rounded-md border border-stone-300 px-3 py-2 font-mono text-sm" /><Button type="button" loading={addAiSources.isPending} disabled={!aiSourceUrl.trim()} onClick={() => addAiSources.mutate([aiSourceUrl.trim()])}>Add AI Document Source</Button></div>
        {aiDiscovery.error || addAiSources.error ? <div className="mt-3"><ErrorBanner error={aiDiscovery.error ?? addAiSources.error} title="AI Document Source request failed" /></div> : null}
      </section>
      {sourceJobs.data?.items.some(
        (job) => job.presentation_status === "waiting_for_worker",
      ) ? (
        <div className="rounded-md border border-amber-200 bg-amber-50 p-4 text-sm text-amber-950">
          Source refresh work is queued and waiting for a background worker.
        </div>
      ) : null}
      <section className="rounded-md border border-stone-200 bg-white p-4 shadow-sm">
        <div className="flex flex-col gap-3 md:flex-row md:items-end">
          <form
            onSubmit={submitSitemap}
            className="flex flex-1 flex-col gap-2 md:flex-row md:items-end"
          >
            <Field id="sitemap-url" label="Sitemap source">
              <input
                id="sitemap-url"
                value={sitemapUrl}
                onChange={(event) => setSitemapUrl(event.target.value)}
                placeholder="https://www.example.com/sitemap.xml"
                className="w-full rounded-md border border-stone-300 px-3 py-2 text-sm"
              />
            </Field>
            <Button type="submit" loading={addSitemap.isPending}>
              Add sitemap
            </Button>
          </form>
          <Button
            type="button"
            loading={robots.isPending}
            onClick={() => robots.mutate()}
          >
            Discover from robots.txt
          </Button>
        </div>
      </section>
      <section className="rounded-md border border-stone-200 bg-white p-4 shadow-sm">
        <h2 className="mb-3 text-base font-semibold">Manual URLs</h2>
        <textarea
          value={manualUrls}
          onChange={(event) => setManualUrls(event.target.value)}
          rows={5}
          className="w-full rounded-md border border-stone-300 px-3 py-2 font-mono text-xs"
          placeholder={"/manual-page/\nhttps://www.example.com/landing"}
        />
        <div className="mt-2">
          <Button
            type="button"
            loading={manual.isPending}
            disabled={!manualUrls.trim()}
            onClick={() => manual.mutate()}
          >
            Add manual URLs
          </Button>
        </div>
        {manual.data ? (
          <div className="mt-2 text-sm text-stone-600">
            {manual.data.accepted_count} accepted - {manual.data.rejected_count}{" "}
            rejected - {manual.data.duplicate_count} duplicates
          </div>
        ) : null}
      </section>
      <section className="rounded-md border border-stone-200 bg-white shadow-sm">
        <h2 className="p-4 text-base font-semibold">Sources</h2>
        {sources.isLoading ? <LoadingBlock label="Loading sources..." /> : null}
        {sources.data?.items.length ? (
          <SourceTable
            sources={sources.data.items}
            jobs={sourceJobs.data?.items ?? []}
            workerHealth={workerHealth.data}
            onRefresh={(source) => refresh.mutate(source)}
            onCancel={(job) => cancelRefresh.mutate(job)}
            onDelete={(source) => {
              if (
                window.confirm(
                  `Delete source ${source.name}? Scan history will be preserved.`,
                )
              )
                remove.mutate(source);
            }}
          />
        ) : !sources.isLoading ? (
          <EmptyState
            title="No sources"
            message="Add a sitemap, discover from robots.txt, or paste manual URLs."
          />
        ) : null}
      </section>
    </div>
  );
}

function SourceTable({
  sources,
  jobs,
  workerHealth,
  onRefresh,
  onCancel,
  onDelete,
}: {
  sources: UrlSource[];
  jobs: Job[];
  workerHealth?: WorkerHealth;
  onRefresh: (source: UrlSource) => void;
  onCancel: (job: Job) => void;
  onDelete: (source: UrlSource) => void;
}) {
  return (
    <div className="overflow-x-auto">
      <table className="min-w-full text-left text-sm">
        <thead className="bg-stone-100 text-xs uppercase text-stone-500">
          <tr>
            {["Source", "Type", "Status", "URLs", "Actions"].map((header) => (
              <th key={header} className="px-3 py-2">
                {header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sources.map((source) => {
            const activeJob = activeSourceJob(jobs, source.id);
            const displayStatus =
              activeJob?.presentation_status ??
              source.last_refresh_status ??
              "never_refreshed";
            const waiting =
              activeJob?.presentation_status === "waiting_for_worker" ||
              (activeJob?.status === "queued" &&
                workerHealth?.queued_work_has_worker === false);
            return (
              <tr key={source.id} className="border-t border-stone-100">
                <td className="max-w-md px-3 py-2">
                  <span className="block font-medium">{source.name}</span>
                  <span className="block truncate font-mono text-xs text-stone-500">
                    {source.source_url ?? "Manual collection"}
                  </span>
                </td>
                <td className="px-3 py-2 capitalize">{source.source_type}</td>
                <td className="px-3 py-2">
                  <StatusBadge
                    status={displayStatus}
                    label={formatStatus(displayStatus)}
                  />
                  {activeJob?.current_operation ? (
                    <span className="mt-1 block text-xs text-stone-500">
                      {activeJob.current_operation}
                    </span>
                  ) : null}
                  {waiting ? (
                    <span className="mt-1 block text-xs text-amber-700">
                      Waiting for worker
                    </span>
                  ) : null}
                </td>
                <td className="px-3 py-2">{source.current_entry_count}</td>
                <td className="px-3 py-2">
                  <div className="flex gap-2">
                    {source.source_type === "ai_document" ? <Link className="underline" to={`/ai-document-sources/${source.id}`}>Open Source</Link> : null}
                    <button
                      type="button"
                      className="underline disabled:text-stone-400"
                      disabled={Boolean(activeJob)}
                      onClick={() => onRefresh(source)}
                    >
                      Refresh
                    </button>
                    {activeJob?.source_refresh_id ? (
                      <button
                        type="button"
                        className="text-red-700 underline"
                        onClick={() => onCancel(activeJob)}
                      >
                        Cancel
                      </button>
                    ) : null}
                    <button
                      type="button"
                      className="text-red-700 underline"
                      onClick={() => onDelete(source)}
                    >
                      Delete
                    </button>
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function activeSourceJob(jobs: Job[], sourceId: number) {
  return jobs.find(
    (job) =>
      !isTerminalStatus(job.status) &&
      Number(job.payload_json.source_id) === sourceId,
  );
}

function InventoryTab({ site }: { site: Site }) {
  const [searchParams, setSearchParams] = useSearchParams();
  const pagination = useUrlPagination({ prefix: "inventory" });
  const query = new URLSearchParams();
  for (const key of [
    "search",
    "source_type",
    "scope_decision",
    "validation_state",
  ]) {
    const value = searchParams.get(key);
    if (value) query.set(key, value);
  }
  query.set("limit", String(pagination.limit));
  query.set("offset", String(pagination.offset));
  const inventory = useQuery({
    queryKey: ["inventory", String(site.id), query.toString()],
    queryFn: () => listInventory(String(site.id), `?${query.toString()}`),
  });
  useEffect(() => pagination.ensureValid(inventory.data?.total), [inventory.data?.total, pagination]);
  const controls = inventory.data ? <PaginatedTableControls total={inventory.data.total} limit={pagination.limit} offset={pagination.offset} onPageChange={pagination.setPage} onPageSizeChange={pagination.setPageSize} itemLabel="inventory URL" isLoading={inventory.isFetching && !inventory.isLoading} /> : null;
  return (
    <section className="rounded-md border border-stone-200 bg-white p-4 shadow-sm">
      <div className="mb-4 grid grid-cols-1 gap-3 md:grid-cols-4">
        <input
          aria-label="Search inventory"
          value={searchParams.get("search") ?? ""}
          onChange={(event) =>
            setSearchParam(setSearchParams, "search", event.target.value)
          }
          placeholder="Search URLs"
          className="rounded-md border border-stone-300 px-3 py-2 text-sm"
        />
        <input
          aria-label="Source type"
          value={searchParams.get("source_type") ?? ""}
          onChange={(event) =>
            setSearchParam(setSearchParams, "source_type", event.target.value)
          }
          placeholder="Source type"
          className="rounded-md border border-stone-300 px-3 py-2 text-sm"
        />
        <input
          aria-label="Scope state"
          value={searchParams.get("scope_decision") ?? ""}
          onChange={(event) =>
            setSearchParam(
              setSearchParams,
              "scope_decision",
              event.target.value,
            )
          }
          placeholder="Scope state"
          className="rounded-md border border-stone-300 px-3 py-2 text-sm"
        />
        <input
          aria-label="Validation state"
          value={searchParams.get("validation_state") ?? ""}
          onChange={(event) =>
            setSearchParam(
              setSearchParams,
              "validation_state",
              event.target.value,
            )
          }
          placeholder="Validation state"
          className="rounded-md border border-stone-300 px-3 py-2 text-sm"
        />
      </div>
      {inventory.isLoading ? (
        <LoadingBlock label="Loading inventory..." />
      ) : null}
      {controls ? <div className="mb-4">{controls}</div> : null}
      {inventory.data?.items.length ? (
        <InventoryTable items={inventory.data.items} />
      ) : !inventory.isLoading ? (
        <EmptyState
          title="No inventory URLs"
          message="Refresh a source or add manual URLs to build this inventory."
        />
      ) : null}
      {controls ? <div className="mt-4">{controls}</div> : null}
    </section>
  );
}

function InventoryTable({ items }: { items: InventoryItem[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="min-w-full text-left text-sm">
        <thead className="bg-stone-100 text-xs uppercase text-stone-500">
          <tr>
            {["URL", "Sources", "Scope", "Validation", "Classification"].map(
              (header) => (
                <th key={header} className="px-3 py-2">
                  {header}
                </th>
              ),
            )}
          </tr>
        </thead>
        <tbody>
          {items.map((item) => (
            <tr
              key={
                item.normalized_url ??
                item.sources.map((source) => source.entry_id).join(",")
              }
              className="border-t border-stone-100 align-top"
            >
              <td className="max-w-xl px-3 py-2 font-mono text-xs">
                {item.normalized_url ?? "Invalid URL"}
              </td>
              <td className="px-3 py-2">
                {item.source_count}
                <details>
                  <summary className="cursor-pointer text-xs underline">
                    View
                  </summary>
                  <ul className="mt-1 space-y-1 text-xs">
                    {item.sources.map((source) => (
                      <li key={String(source.entry_id)}>
                        {String(source.name)} - {String(source.type)}
                      </li>
                    ))}
                  </ul>
                </details>
              </td>
              <td className="px-3 py-2">{item.scope_decision}</td>
              <td className="px-3 py-2">{item.validation_state}</td>
              <td className="px-3 py-2">{item.classification}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ScopeSummary({ site }: { site: Site }) {
  const scope = site.scope_config;
  const allowed = scope.allowed_host_patterns.length;
  const included = scope.included_path_prefixes.filter(
    (path) => path !== "/",
  ).length;
  return (
    <div className="flex flex-wrap gap-2 text-xs">
      <span className="rounded-md border border-stone-200 bg-stone-50 px-2 py-1">
        {allowed
          ? plural(allowed, "allowed host")
          : `Exact hostname from ${new URL(site.base_url).hostname}`}
      </span>
      <span className="rounded-md border border-stone-200 bg-stone-50 px-2 py-1">
        {scope.follow_subdomains
          ? "Subdomains included"
          : "Subdomains excluded"}
      </span>
      <span className="rounded-md border border-stone-200 bg-stone-50 px-2 py-1">
        {included ? plural(included, "included path") : "All paths included"}
      </span>
      <span className="rounded-md border border-stone-200 bg-stone-50 px-2 py-1">
        Maximum {scope.max_pages} pages
      </span>
      <span className="rounded-md border border-stone-200 bg-stone-50 px-2 py-1">
        Maximum depth {scope.max_depth}
      </span>
    </div>
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

function setSearchParam(
  setSearchParams: ReturnType<typeof useSearchParams>[1],
  key: string,
  value: string,
) {
  setSearchParams((current) => {
    const next = new URLSearchParams(current);
    if (value) next.set(key, value);
    else next.delete(key);
    if (next.get("tab") === "pages") next.delete("site_pages_offset");
    if (next.get("tab") === "inventory") next.delete("inventory_offset");
    return next;
  });
}
