import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FormEvent, useState } from "react";

import {
  createCategoryRule,
  deleteCategoryRule,
  evaluateCategoryRules,
  getCategoryRuleDeletePreview,
  listCategoryRuleRuns,
  listCategoryRules,
  previewCategoryRule,
  updateCategoryRule,
  type CategoryRulePayload,
} from "../api/client";
import type { CategoryRule, CategoryRuleCondition, PageCategory } from "../types/scans";
import { formatDate, formatStatus, plural } from "../utils/format";
import { Button } from "./ui/Button";
import { EmptyState } from "./ui/EmptyState";
import { ErrorBanner } from "./ui/ErrorBanner";
import { LoadingBlock } from "./ui/Loading";
import { PaginatedTableControls } from "./ui/PaginatedTableControls";
import { StatusBadge } from "./ui/StatusBadge";
import { SortableTableHeader, type SortDirection } from "./ui/SortableTableHeader";

const emptyCondition = (): CategoryRuleCondition => ({
  target: "path",
  operator: "starts_with",
  value: "",
  negate: false,
  case_sensitive: false,
  sort_order: 0,
});

export function CategoryRulesPanel({ siteId, categories, timeZone }: { siteId: string; categories: PageCategory[]; timeZone: string | null }) {
  const queryClient = useQueryClient();
  const [offset, setOffset] = useState(0);
  const [search, setSearch] = useState("");
  const [editing, setEditing] = useState<CategoryRule | null>(null);
  const [creating, setCreating] = useState(false);
  const [sortColumn, setSortColumn] = useState<string | null>(null);
  const [sortDirection, setSortDirection] = useState<SortDirection | null>(null);
  const sortQuery = sortColumn && sortDirection ? `&sort=${sortColumn}&direction=${sortDirection}` : "";
  const rules = useQuery({
    queryKey: ["category-rules", siteId, search, offset, sortColumn, sortDirection],
    queryFn: () => listCategoryRules(siteId, `?limit=25&offset=${offset}&search=${encodeURIComponent(search)}${sortQuery}`),
  });
  const recalculate = useMutation({
    mutationFn: () => evaluateCategoryRules(siteId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["category-rule-runs", siteId] }),
  });
  const refresh = async () => {
    await queryClient.invalidateQueries({ queryKey: ["category-rules", siteId] });
    await queryClient.invalidateQueries({ queryKey: ["category-rule-runs", siteId] });
    await queryClient.invalidateQueries({ queryKey: ["site-pages", siteId] });
  };
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <label className="text-sm font-medium">Search Rules<input aria-label="Search Rules" value={search} onChange={(event) => { setSearch(event.target.value); setOffset(0); }} className="mt-1 block rounded-md border border-stone-300 px-3 py-2" /></label>
        <div className="flex gap-2"><Button type="button" onClick={() => setCreating(true)}>Create Rule</Button><Button type="button" onClick={() => recalculate.mutate()} loading={recalculate.isPending}>Recalculate</Button></div>
      </div>
      {creating || editing ? <RuleEditor siteId={siteId} categories={categories.filter((item) => item.is_active)} rule={editing} onClose={() => { setCreating(false); setEditing(null); }} onSaved={refresh} /> : null}
      {rules.error || recalculate.error ? <ErrorBanner error={rules.error ?? recalculate.error} title="Category Rule action failed" /> : null}
      {rules.isLoading ? <LoadingBlock label="Loading Category Rules..." /> : null}
      {rules.data?.items.length ? <div className="overflow-x-auto rounded-md border border-stone-200 bg-white"><table className="min-w-full text-left text-sm"><thead className="bg-stone-100 text-xs uppercase text-stone-500"><tr>{[["active", "Active"], ["name", "Rule"], ["category", "Category"], ["mode", "Mode"], ["condition_count", "Conditions"], ["match_count", "Matches"], ["excluded_count", "Excluded"], ["last_evaluated_at", "Last evaluated"]].map(([column, label]) => <SortableTableHeader key={column} column={column} label={label} activeColumn={sortColumn} direction={sortDirection} onChange={(column, direction) => { setSortColumn(column); setSortDirection(direction); setOffset(0); }} defaultDirection={column === "last_evaluated_at" ? "desc" : "asc"} />)}<th className="px-3 py-2 font-medium">Actions</th></tr></thead><tbody>{rules.data.items.map((rule) => <RuleRow key={rule.id} rule={rule} siteId={siteId} timeZone={timeZone} edit={() => setEditing(rule)} refresh={refresh} />)}</tbody></table></div> : !rules.isLoading ? <EmptyState title="No Category Rules" message="Create a deterministic URL Rule to organize this Site's Pages." /> : null}
      {rules.data ? <PaginatedTableControls total={rules.data.total} limit={25} offset={offset} onPageChange={(page) => setOffset((page - 1) * 25)} onPageSizeChange={() => undefined} itemLabel="Rule" isLoading={rules.isFetching} allowedPageSizes={[25]} /> : null}
    </div>
  );
}

function RuleRow({ rule, siteId, timeZone, edit, refresh }: { rule: CategoryRule; siteId: string; timeZone: string | null; edit: () => void; refresh: () => Promise<void> }) {
  const toggle = useMutation({ mutationFn: () => updateCategoryRule(siteId, rule.id, { is_active: !rule.is_active }), onSuccess: refresh });
  const remove = useMutation({
    mutationFn: async () => {
      const preview = await getCategoryRuleDeletePreview(siteId, rule.id);
      if (!window.confirm(`Delete ${rule.name}? ${plural(preview.effective_assignments_removed, "assignment")} will disappear; ${preview.effective_assignments_retained} will remain supported.`)) throw new Error("Deletion cancelled");
      return deleteCategoryRule(siteId, rule.id);
    },
    onSuccess: refresh,
  });
  return <tr className="border-t border-stone-100 align-top"><td className="px-3 py-2"><input type="checkbox" aria-label={`${rule.name} active`} checked={rule.is_active} onChange={() => toggle.mutate()} /></td><td className="px-3 py-2 font-medium">{rule.name}<span className="block text-xs font-normal text-stone-500">Revision {rule.current_revision_number}</span></td><td className="px-3 py-2">{rule.category_name}</td><td className="px-3 py-2">{formatStatus(rule.match_mode)}</td><td className="px-3 py-2">{rule.conditions.length}</td><td className="px-3 py-2">{rule.current_match_count}</td><td className="px-3 py-2">{rule.current_excluded_count}</td><td className="whitespace-nowrap px-3 py-2">{formatDate(rule.last_evaluated_at, { timeZone, showTimeZone: true })}</td><td className="px-3 py-2"><div className="flex gap-2"><Button type="button" onClick={edit}>Edit</Button><Button type="button" variant="danger" onClick={() => remove.mutate()} loading={remove.isPending}>Delete</Button></div>{toggle.error || (remove.error && remove.error.message !== "Deletion cancelled") ? <div className="mt-2 text-xs text-red-700">Action failed</div> : null}</td></tr>;
}

function RuleEditor({ siteId, categories, rule, onClose, onSaved }: { siteId: string; categories: PageCategory[]; rule: CategoryRule | null; onClose: () => void; onSaved: () => Promise<void> }) {
  const [name, setName] = useState(rule?.name ?? "");
  const [description, setDescription] = useState(rule?.description ?? "");
  const [categoryId, setCategoryId] = useState(rule?.category_id ?? categories[0]?.id ?? 0);
  const [matchMode, setMatchMode] = useState<"all" | "any">(rule?.match_mode ?? "all");
  const [conditions, setConditions] = useState<CategoryRuleCondition[]>(rule?.conditions.map(({ target, operator, value, negate, case_sensitive, sort_order }) => ({ target, operator, value, negate, case_sensitive, sort_order })) ?? [emptyCondition()]);
  const [previewData, setPreviewData] = useState<Awaited<ReturnType<typeof previewCategoryRule>> | null>(null);
  const payload = (): CategoryRulePayload => ({ name, description: description || null, category_id: categoryId, match_mode: matchMode, conditions: conditions.map((item, index) => ({ ...item, sort_order: index })) });
  const preview = useMutation({ mutationFn: () => previewCategoryRule(siteId, { ...payload(), rule_id: rule?.id }), onSuccess: setPreviewData });
  const save = useMutation({ mutationFn: () => rule ? updateCategoryRule(siteId, rule.id, payload()) : createCategoryRule(siteId, payload()), onSuccess: async () => { await onSaved(); onClose(); } });
  const valid = Boolean(name.trim() && categoryId && conditions.length && conditions.every((item) => item.value));
  const changeCondition = (index: number, update: Partial<CategoryRuleCondition>) => setConditions((items) => items.map((item, itemIndex) => itemIndex === index ? { ...item, ...update } : item));
  const moveCondition = (index: number, direction: -1 | 1) => setConditions((items) => {
    const nextIndex = index + direction;
    if (nextIndex < 0 || nextIndex >= items.length) return items;
    const reordered = [...items];
    [reordered[index], reordered[nextIndex]] = [reordered[nextIndex], reordered[index]];
    return reordered;
  });
  const submit = (event: FormEvent) => { event.preventDefault(); if (valid) preview.mutate(); };
  return <form onSubmit={submit} className="space-y-4 border-y border-stone-200 bg-white py-4"><h3 className="text-base font-semibold">{rule ? "Edit Rule" : "Create Rule"}</h3><div className="grid gap-3 md:grid-cols-2"><label className="text-sm font-medium">Rule name<input aria-label="Rule name" value={name} onChange={(event) => setName(event.target.value)} className="mt-1 w-full rounded-md border border-stone-300 px-3 py-2" /></label><label className="text-sm font-medium">Category<select aria-label="Rule Category" value={categoryId} onChange={(event) => setCategoryId(Number(event.target.value))} className="mt-1 w-full rounded-md border border-stone-300 px-3 py-2"><option value={0}>Choose Category</option>{categories.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label><label className="text-sm font-medium md:col-span-2">Description<textarea value={description} onChange={(event) => setDescription(event.target.value)} rows={2} className="mt-1 w-full rounded-md border border-stone-300 px-3 py-2" /></label></div><fieldset><legend className="text-sm font-medium">Match conditions</legend><div className="mt-2 inline-flex rounded-md border border-stone-300 p-1"><button type="button" aria-pressed={matchMode === "all"} onClick={() => setMatchMode("all")} className={`px-3 py-1 text-sm ${matchMode === "all" ? "bg-stone-900 text-white" : ""}`}>All</button><button type="button" aria-pressed={matchMode === "any"} onClick={() => setMatchMode("any")} className={`px-3 py-1 text-sm ${matchMode === "any" ? "bg-stone-900 text-white" : ""}`}>Any</button></div><div className="mt-3 space-y-3">{conditions.map((condition, index) => <ConditionRow key={index} condition={condition} index={index} change={changeCondition} move={(direction) => moveCondition(index, direction)} canMoveUp={index > 0} canMoveDown={index < conditions.length - 1} remove={() => setConditions((items) => items.filter((_, itemIndex) => itemIndex !== index))} />)}</div><Button type="button" onClick={() => setConditions((items) => [...items, emptyCondition()])}>Add condition</Button></fieldset>{previewData ? <section aria-label="Rule preview" className="border-l-4 border-teal-600 pl-4 text-sm"><div className="font-medium">Preview: {plural(previewData.matching_pages, "matching Page")}</div><p>{previewData.would_gain_automatic_support} gain support, {previewData.would_lose_automatic_support} lose support, {previewData.excluded_matches} excluded.</p><ul className="mt-2 space-y-1 font-mono text-xs">{previewData.sample_matching_pages.map((item) => <li key={item.resource_id}>{item.normalized_url}</li>)}</ul></section> : null}{preview.error || save.error ? <ErrorBanner error={preview.error ?? save.error} title="Could not save Rule" /> : null}<div className="flex justify-end gap-2"><Button type="button" onClick={onClose}>Cancel</Button><Button type="submit" disabled={!valid} loading={preview.isPending}>Preview</Button><Button type="button" disabled={!valid || !previewData} loading={save.isPending} onClick={() => save.mutate()}>Save & Apply</Button></div></form>;
}

function ConditionRow({ condition, index, change, move, canMoveUp, canMoveDown, remove }: { condition: CategoryRuleCondition; index: number; change: (index: number, update: Partial<CategoryRuleCondition>) => void; move: (direction: -1 | 1) => void; canMoveUp: boolean; canMoveDown: boolean; remove: () => void }) {
  const targets: CategoryRuleCondition["target"][] = ["normalized_url", "host", "path", "query", "filename"];
  const operators: CategoryRuleCondition["operator"][] = ["equals", "starts_with", "ends_with", "contains", "glob", "regex"];
  return <div className="grid gap-2 border-l-2 border-stone-200 pl-3 md:grid-cols-[150px_150px_minmax(180px,1fr)_auto]"><label className="text-xs">Target<select aria-label={`Condition ${index + 1} target`} value={condition.target} onChange={(event) => change(index, { target: event.target.value as CategoryRuleCondition["target"], case_sensitive: event.target.value === "host" ? false : condition.case_sensitive })} className="mt-1 w-full rounded-md border border-stone-300 px-2 py-2 text-sm">{targets.map((item) => <option key={item} value={item}>{formatStatus(item)}</option>)}</select></label><label className="text-xs">Operator<select aria-label={`Condition ${index + 1} operator`} value={condition.operator} onChange={(event) => change(index, { operator: event.target.value as CategoryRuleCondition["operator"] })} className="mt-1 w-full rounded-md border border-stone-300 px-2 py-2 text-sm">{operators.map((item) => <option key={item} value={item}>{formatStatus(item)}</option>)}</select></label><label className="text-xs">Value<input aria-label={`Condition ${index + 1} value`} value={condition.value} onChange={(event) => change(index, { value: event.target.value })} className="mt-1 w-full rounded-md border border-stone-300 px-2 py-2 font-mono text-sm" /></label><div className="flex flex-wrap items-end gap-2 pb-2"><label className="text-xs"><input type="checkbox" checked={condition.negate} onChange={(event) => change(index, { negate: event.target.checked })} /> Not</label>{condition.target !== "host" ? <label className="text-xs"><input type="checkbox" checked={condition.case_sensitive} onChange={(event) => change(index, { case_sensitive: event.target.checked })} /> Case</label> : null}<Button type="button" onClick={() => move(-1)} disabled={!canMoveUp} aria-label={`Move condition ${index + 1} up`}>Up</Button><Button type="button" onClick={() => move(1)} disabled={!canMoveDown} aria-label={`Move condition ${index + 1} down`}>Down</Button><Button type="button" onClick={remove}>Remove</Button></div></div>;
}

export function CategoryRuleHistoryPanel({ siteId, timeZone }: { siteId: string; timeZone: string | null }) {
  const [offset, setOffset] = useState(0);
  const [sortColumn, setSortColumn] = useState<string | null>(null);
  const [sortDirection, setSortDirection] = useState<SortDirection | null>(null);
  const sortQuery = sortColumn && sortDirection ? `&sort=${sortColumn}&direction=${sortDirection}` : "";
  const runs = useQuery({ queryKey: ["category-rule-runs", siteId, offset, sortColumn, sortDirection], queryFn: () => listCategoryRuleRuns(siteId, `?limit=25&offset=${offset}${sortQuery}`), refetchInterval: (query) => query.state.data?.items.some((item) => item.status === "queued" || item.status === "running") ? 1500 : false });
  if (runs.isLoading) return <LoadingBlock label="Loading Rule evaluation history..." />;
  if (runs.error) return <ErrorBanner error={runs.error} title="Could not load evaluation history" />;
  if (!runs.data?.items.length) return <EmptyState title="No evaluations" message="Rule evaluations will appear here after a Rule is saved or recalculated." />;
  return <div className="space-y-4"><div className="overflow-x-auto rounded-md border border-stone-200 bg-white"><table className="min-w-full text-left text-sm"><thead className="bg-stone-100 text-xs uppercase text-stone-500"><tr>{[["trigger", "Trigger"], ["status", "Status"], ["started_at", "Started"], ["page_count", "Pages"], ["rule_count", "Rules"], ["match_count", "Matches"], ["supports_delta", "Supports + / -"], ["assignments_delta", "Assignments + / -"], ["excluded_count", "Excluded"], ["evaluator", "Evaluator"]].map(([column, label]) => <SortableTableHeader key={column} column={column} label={label} activeColumn={sortColumn} direction={sortDirection} onChange={(column, direction) => { setSortColumn(column); setSortDirection(direction); setOffset(0); }} defaultDirection={column === "started_at" ? "desc" : "asc"} />)}</tr></thead><tbody>{runs.data.items.map((run) => <tr key={run.id} className="border-t border-stone-100"><td className="px-3 py-2">{formatStatus(run.trigger_type)}</td><td className="px-3 py-2"><StatusBadge status={run.status} /></td><td className="whitespace-nowrap px-3 py-2">{formatDate(run.started_at ?? run.created_at, { timeZone, showTimeZone: true })}</td><td className="px-3 py-2">{run.page_count}</td><td className="px-3 py-2">{run.rule_count}</td><td className="px-3 py-2">{run.match_count}</td><td className="px-3 py-2">{run.rule_supports_added} / {run.rule_supports_removed}</td><td className="px-3 py-2">{run.effective_assignments_added} / {run.effective_assignments_removed}</td><td className="px-3 py-2">{run.exclusions_suppressing_matches}</td><td className="px-3 py-2 font-mono text-xs">{run.evaluator_version}</td></tr>)}</tbody></table></div><PaginatedTableControls total={runs.data.total} limit={25} offset={offset} onPageChange={(page) => setOffset((page - 1) * 25)} onPageSizeChange={() => undefined} itemLabel="evaluation" isLoading={runs.isFetching} allowedPageSizes={[25]} /></div>;
}
