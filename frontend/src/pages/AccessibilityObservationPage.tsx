import { useQuery } from "@tanstack/react-query";
import { ExternalLink } from "lucide-react";
import { useState } from "react";
import { Link, useOutletContext, useParams } from "react-router-dom";

import {
  getAccessibilityObservation,
  getAccessibilityObservationNodes,
  getAccessibilityObservationRules,
} from "../api/client";
import { Button } from "../components/ui/Button";
import { DefinitionList } from "../components/ui/DefinitionList";
import { EmptyState } from "../components/ui/EmptyState";
import { ErrorBanner } from "../components/ui/ErrorBanner";
import { LoadingBlock } from "../components/ui/Loading";
import { StatusBadge } from "../components/ui/StatusBadge";
import type { AccessibilityRule } from "../types/accessibility";
import type { Site } from "../types/scans";
import { formatDate, formatStatus } from "../utils/format";

type WorkspaceContext = { site: Site };

export function AccessibilityObservationPage() {
  const { site } = useOutletContext<WorkspaceContext>();
  const { observationId = "" } = useParams();
  const id = Number(observationId);
  const [ruleSearch, setRuleSearch] = useState("");
  const [impact, setImpact] = useState("all");
  const observation = useQuery({
    queryKey: ["accessibility-observation", String(site.id), id],
    queryFn: () => getAccessibilityObservation(String(site.id), id),
  });
  const rules = useQuery({
    queryKey: ["accessibility-observation-rules", String(site.id), id],
    queryFn: () =>
      getAccessibilityObservationRules(String(site.id), id, "?limit=200"),
  });
  if (observation.isLoading || rules.isLoading)
    return <LoadingBlock label="Loading Accessibility result..." />;
  if (observation.error)
    return (
      <ErrorBanner
        error={observation.error}
        title="Could not load Accessibility result"
      />
    );
  if (rules.error)
    return (
      <ErrorBanner
        error={rules.error}
        title="Could not load Accessibility evidence"
      />
    );
  if (!observation.data) return null;
  const value = observation.data;
  const violations =
    rules.data?.items.filter((rule) => rule.result_type === "violation") ?? [];
  const incomplete =
    rules.data?.items.filter((rule) => rule.result_type === "incomplete") ?? [];
  const visible = (items: AccessibilityRule[]) =>
    items.filter(
      (rule) =>
        (impact === "all" ||
          (impact === "unknown" ? !rule.impact : rule.impact === impact)) &&
        (!ruleSearch ||
          `${rule.rule_id} ${rule.help} ${rule.description}`
            .toLocaleLowerCase()
            .includes(ruleSearch.toLocaleLowerCase())),
    );
  const impactCounts = ["critical", "serious", "moderate", "minor"].map(
    (name) => ({
      name,
      rules: violations.filter((rule) => rule.impact === name).length,
      elements: violations
        .filter((rule) => rule.impact === name)
        .reduce((total, rule) => total + rule.node_count, 0),
    }),
  );
  return (
    <div className="space-y-5">
      <header>
        <Link
          className="text-sm underline"
          to={`/sites/${site.id}/accessibility/runs/${value.accessibility_run_id}`}
        >
          Run {value.accessibility_run_id}
        </Link>
        <h1 className="mt-1 text-xl font-semibold">
          Accessibility observation
        </h1>
        <p className="mt-1 break-all font-mono text-xs text-stone-600">
          {value.requested_url}
        </p>
        <p className="mt-1 text-sm text-stone-600">
          {formatStatus(value.profile)} · Audited{" "}
          {formatDate(value.observed_at)}
        </p>
      </header>
      <section className="grid gap-px overflow-hidden rounded-md border border-stone-200 bg-stone-200 sm:grid-cols-2 lg:grid-cols-4">
        <Summary label="Profile" value={formatStatus(value.profile)} />
        <Summary
          label="Violations"
          value={`${value.violation_rule_count} rules / ${value.violation_node_count} elements`}
        />
        <Summary
          label="Needs Review"
          value={`${value.incomplete_rule_count} rules / ${value.incomplete_node_count} elements`}
        />
        <Summary label="Outcome" value={formatStatus(value.outcome)} />
        {impactCounts.map((count) => (
          <Summary
            key={count.name}
            label={formatStatus(count.name)}
            value={`${count.rules} rules / ${count.elements} elements`}
          />
        ))}
      </section>
      {value.outcome === "failed" ? (
        <p className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-800">
          {value.error_message ?? "Accessibility collection failed."}
        </p>
      ) : null}
      <section className="grid gap-3 border-y border-stone-200 py-4 sm:grid-cols-[1fr_12rem]">
        <label className="text-sm">
          <span className="mb-1 block font-medium">
            Search this observation
          </span>
          <input
            value={ruleSearch}
            onChange={(event) => setRuleSearch(event.target.value)}
            placeholder="Rule ID, help, or description"
            className="w-full rounded-md border border-stone-300 px-3 py-2"
          />
        </label>
        <label className="text-sm">
          <span className="mb-1 block font-medium">Impact</span>
          <select
            value={impact}
            onChange={(event) => setImpact(event.target.value)}
            className="w-full rounded-md border border-stone-300 px-3 py-2"
          >
            <option value="all">All impacts</option>
            <option value="critical">Critical</option>
            <option value="serious">Serious</option>
            <option value="moderate">Moderate</option>
            <option value="minor">Minor</option>
            <option value="unknown">Unknown</option>
          </select>
        </label>
      </section>
      <RuleSection
        title="Violations"
        description="Automated detector failures."
        rules={visible(violations)}
        siteId={String(site.id)}
        observationId={id}
      />
      <RuleSection
        title="Needs Review"
        description="Incomplete checks that require human review."
        rules={visible(incomplete)}
        siteId={String(site.id)}
        observationId={id}
      />
      <section className="border-t border-stone-200 pt-4">
        <h2 className="font-semibold">Technical evidence</h2>
        <div className="mt-3">
          <DefinitionList
            items={[
              { label: "Requested URL", value: value.requested_url },
              { label: "Final URL", value: value.final_url ?? "Not available" },
              { label: "Observed", value: formatDate(value.observed_at) },
              { label: "axe-core", value: value.axe_core_version },
              {
                label: "Detector SHA-256",
                value: value.detector_bundle_sha256,
                copyValue: value.detector_bundle_sha256,
              },
              { label: "Ruleset", value: value.ruleset_profile },
              {
                label: "Ruleset SHA-256",
                value: value.ruleset_sha256,
                copyValue: value.ruleset_sha256,
              },
              {
                label: "Browser",
                value:
                  `${value.browser_engine} ${value.browser_version ?? ""}`.trim(),
              },
              {
                label: "Playwright",
                value: value.playwright_version ?? "Not reported",
              },
              { label: "Normalization", value: value.normalization_version },
              {
                label: "Payload SHA-256",
                value: value.payload_sha256,
                copyValue: value.payload_sha256,
              },
            ]}
          />
        </div>
        {value.payload_sha256 ? (
          <Link
            className="mt-4 inline-flex items-center gap-1 text-sm underline"
            to={`/sites/${site.id}/accessibility/evidence/${value.id}`}
          >
            View exact raw detector JSON <ExternalLink size={14} />
          </Link>
        ) : null}
      </section>
    </div>
  );
}

function Summary({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0 bg-white p-4">
      <div className="text-xs font-medium text-stone-500">{label}</div>
      <div className="mt-1 text-base font-semibold">{value}</div>
    </div>
  );
}

function RuleSection({
  title,
  description,
  rules,
  siteId,
  observationId,
}: {
  title: string;
  description: string;
  rules: AccessibilityRule[];
  siteId: string;
  observationId: number;
}) {
  return (
    <section>
      <h2 className="font-semibold">{title}</h2>
      <p className="text-sm text-stone-600">{description}</p>
      {rules.length ? (
        <div className="mt-3 divide-y border-y border-stone-200">
          {rules.map((rule) => (
            <RuleItem
              key={rule.id}
              rule={rule}
              siteId={siteId}
              observationId={observationId}
            />
          ))}
        </div>
      ) : (
        <EmptyState
          title={`No ${title}`}
          message={`This observation contains no ${title.toLowerCase()} evidence.`}
        />
      )}
    </section>
  );
}

function RuleItem({
  rule,
  siteId,
  observationId,
}: {
  rule: AccessibilityRule;
  siteId: string;
  observationId: number;
}) {
  const [expanded, setExpanded] = useState(false);
  const [offset, setOffset] = useState(0);
  const nodes = useQuery({
    queryKey: [
      "accessibility-observation-nodes",
      siteId,
      observationId,
      rule.id,
      offset,
    ],
    queryFn: () =>
      getAccessibilityObservationNodes(
        siteId,
        observationId,
        rule.id,
        `?limit=25&offset=${offset}`,
      ),
    enabled: expanded,
  });
  return (
    <article className="py-3">
      <button
        type="button"
        className="flex w-full items-start justify-between gap-3 text-left"
        aria-expanded={expanded}
        onClick={() => setExpanded((value) => !value)}
      >
        <span>
          <strong>{rule.help || rule.rule_id}</strong>
          <span className="mt-1 block font-mono text-xs text-stone-500">
            {rule.rule_id}
          </span>
        </span>
        <span className="shrink-0 text-sm">{rule.node_count} elements</span>
      </button>
      <div className="mt-2 flex flex-wrap gap-2">
        <StatusBadge
          status={
            rule.result_type === "incomplete" ? "needs_review" : "violation"
          }
          label={
            rule.result_type === "incomplete" ? "Needs Review" : "Violation"
          }
        />
        <span className="rounded-md border border-stone-300 px-2 py-1 text-xs">
          {formatStatus(rule.impact)}
        </span>
        {rule.tags_json
          .filter((tag) => tag.startsWith("wcag"))
          .map((tag) => (
            <span
              key={tag}
              className="rounded-md bg-stone-100 px-2 py-1 text-xs"
            >
              {tag}
            </span>
          ))}
      </div>
      {expanded ? (
        <div className="mt-3 space-y-3">
          {nodes.isLoading ? (
            <LoadingBlock label="Loading affected elements..." />
          ) : nodes.error ? (
            <ErrorBanner
              error={nodes.error}
              title="Could not load affected elements"
            />
          ) : (
            nodes.data?.items.map((node) => (
              <div
                key={node.id}
                className="border-l-2 border-stone-300 pl-3 text-sm"
              >
                <div>
                  <strong>Target:</strong>{" "}
                  <code className="break-all">
                    {JSON.stringify(node.target_json)}
                  </code>
                </div>
                <p className="mt-2 whitespace-pre-wrap">
                  {node.failure_summary}
                </p>
                <div className="mt-2">
                  <strong>
                    HTML{node.html_truncated ? " (truncated)" : ""}
                  </strong>
                  <pre className="mt-1 max-h-40 overflow-auto whitespace-pre-wrap break-all rounded bg-stone-950 p-3 text-xs text-stone-100">
                    {node.html_snippet}
                  </pre>
                </div>
              </div>
            ))
          )}
          {nodes.data && nodes.data.total > nodes.data.limit ? (
            <div className="flex items-center gap-2">
              <Button
                type="button"
                disabled={!offset}
                onClick={() => setOffset(Math.max(0, offset - 25))}
              >
                Previous elements
              </Button>
              <span className="text-xs">
                {offset + 1}-{Math.min(offset + 25, nodes.data.total)} of{" "}
                {nodes.data.total}
              </span>
              <Button
                type="button"
                disabled={offset + 25 >= nodes.data.total}
                onClick={() => setOffset(offset + 25)}
              >
                Next elements
              </Button>
            </div>
          ) : null}
          {rule.help_url ? (
            <a
              className="inline-flex items-center gap-1 text-sm underline"
              href={rule.help_url}
              target="_blank"
              rel="noreferrer"
            >
              Open axe guidance <ExternalLink size={14} />
            </a>
          ) : null}
        </div>
      ) : null}
    </article>
  );
}
