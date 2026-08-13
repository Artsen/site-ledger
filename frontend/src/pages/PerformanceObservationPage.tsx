import { useQuery } from "@tanstack/react-query";
import { ExternalLink } from "lucide-react";
import { Link, useOutletContext, useParams } from "react-router-dom";

import { getPerformanceObservationPresentation } from "../api/client";
import { DefinitionList } from "../components/ui/DefinitionList";
import { ErrorBanner } from "../components/ui/ErrorBanner";
import { LoadingBlock } from "../components/ui/Loading";
import { StatusBadge } from "../components/ui/StatusBadge";
import type {
  PerformanceMetricPresentation,
  PerformanceObservation,
} from "../types/performance";
import type { Site } from "../types/scans";
import { formatDate, formatStatus } from "../utils/format";

type WorkspaceContext = { site: Site };

export function PerformanceObservationPage() {
  const { site } = useOutletContext<WorkspaceContext>();
  const { observationId = "" } = useParams();
  const detail = useQuery({
    queryKey: [
      "performance-observation-presentation",
      String(site.id),
      observationId,
    ],
    queryFn: () =>
      getPerformanceObservationPresentation(
        String(site.id),
        Number(observationId),
      ),
  });
  if (detail.isLoading)
    return <LoadingBlock label="Loading Performance result..." />;
  if (detail.error)
    return (
      <ErrorBanner
        error={detail.error}
        title="Could not load Performance result"
      />
    );
  if (!detail.data) return null;
  const {
    observation,
    metrics,
    opportunities,
    diagnostics,
    origin_context: origin,
    origin_metrics: originMetrics,
  } = detail.data;
  const unavailable =
    observation.provider === "crux" && observation.outcome === "unavailable";
  return (
    <div className="space-y-5">
      <header>
        <Link
          className="text-sm underline"
          to={`/sites/${site.id}/performance/runs/${observation.performance_run_id}`}
        >
          Run {observation.performance_run_id}
        </Link>
        <h1 className="mt-1 text-xl font-semibold">
          {observation.provider === "pagespeed"
            ? "PageSpeed Lab result"
            : "Real-user experience"}
        </h1>
        <p className="mt-1 break-all font-mono text-xs text-stone-600">
          {observation.requested_target}
        </p>
        <p className="mt-1 text-sm text-stone-600">
          Collected {formatDate(observation.observed_at)}
          {formatCollectionPeriod(observation.provider_period_json)
            ? ` · ${formatCollectionPeriod(observation.provider_period_json)}`
            : ""}
        </p>
      </header>
      <section className="border-y border-stone-200 py-4">
        <div className="flex flex-wrap items-center gap-2">
          <strong>{formatStatus(observation.dimension)}</strong>
          <StatusBadge
            status={observation.outcome}
            label={unavailable ? "URL-level field data unavailable" : undefined}
          />
        </div>
        {unavailable ? (
          <p className="mt-2 max-w-2xl text-sm text-stone-700">
            This Page does not have enough qualifying real-user Chrome data for
            URL-level reporting. Collection completed normally.
          </p>
        ) : null}
        {observation.outcome === "failed" ? (
          <p className="mt-2 text-sm text-red-700">
            {observation.error_message ?? "Provider collection failed."}
          </p>
        ) : null}
      </section>
      {metrics.length ? <MetricGrid metrics={metrics} /> : null}
      {unavailable && origin ? (
        <OriginContext observation={origin} metrics={originMetrics} />
      ) : null}
      {unavailable && !origin ? (
        <p className="rounded-md border border-stone-200 bg-stone-50 p-3 text-sm">
          No same-run Site-origin field evidence is available for this form
          factor.
        </p>
      ) : null}
      {opportunities.length ? (
        <AuditList title="Optimization opportunities" items={opportunities} />
      ) : null}
      {diagnostics.length ? (
        <AuditList title="Diagnostics" items={diagnostics} />
      ) : null}
      {detail.data.presentation_error ? (
        <p className="rounded-md border border-amber-200 bg-amber-50 p-3 text-sm">
          {detail.data.presentation_error}
        </p>
      ) : null}
      <section className="border-t border-stone-200 pt-4">
        <h2 className="font-semibold">Technical evidence</h2>
        <div className="mt-3">
          <DefinitionList
            items={[
              {
                label: "Provider adapter",
                value: observation.provider_adapter_version,
              },
              {
                label: "Normalization",
                value: observation.normalization_version,
              },
              {
                label: "Provider target",
                value: observation.provider_target ?? "Not returned",
              },
              {
                label: "Provider product",
                value: observation.provider_product_version ?? "Not returned",
              },
              { label: "Observed", value: formatDate(observation.observed_at) },
              {
                label: "Payload SHA-256",
                value: observation.payload_sha256,
                copyValue: observation.payload_sha256,
              },
            ]}
          />
        </div>
        {observation.payload_sha256 ? (
          <Link
            className="mt-4 inline-flex items-center gap-1 text-sm underline"
            to={`/sites/${site.id}/performance/evidence/${observation.id}`}
          >
            View exact raw JSON <ExternalLink size={14} />
          </Link>
        ) : null}
      </section>
    </div>
  );
}

function formatCollectionPeriod(period: Record<string, unknown> | null) {
  if (!period) return null;
  const firstDate = formatProviderDate(period.firstDate);
  const lastDate = formatProviderDate(period.lastDate);
  if (firstDate && lastDate) {
    return `Field period ${firstDate} to ${lastDate}`;
  }
  return null;
}

function formatProviderDate(value: unknown) {
  if (typeof value === "string") return value;
  if (!value || typeof value !== "object") return null;
  const date = value as Record<string, unknown>;
  if (
    typeof date.year !== "number" ||
    typeof date.month !== "number" ||
    typeof date.day !== "number"
  ) {
    return null;
  }
  return `${date.year}-${String(date.month).padStart(2, "0")}-${String(date.day).padStart(2, "0")}`;
}

function MetricGrid({ metrics }: { metrics: PerformanceMetricPresentation[] }) {
  return (
    <section>
      <h2 className="font-semibold">Metrics</h2>
      <div className="mt-3 grid gap-px overflow-hidden rounded-md border border-stone-200 bg-stone-200 sm:grid-cols-2 lg:grid-cols-3">
        {metrics.map((metric) => (
          <div key={metric.key} className="min-w-0 bg-white p-4">
            <div className="text-xs font-medium text-stone-600">
              {metric.label}
            </div>
            <div className="mt-1 text-xl font-semibold tabular-nums">
              {metric.formatted_value}
            </div>
            {metric.assessment ? (
              <span className="mt-1 block text-sm">
                {formatStatus(metric.assessment)}
              </span>
            ) : null}
            {metric.histogram.length ? (
              <Histogram values={metric.histogram} />
            ) : null}
          </div>
        ))}
      </div>
    </section>
  );
}

function Histogram({ values }: { values: Array<Record<string, number>> }) {
  const labels = ["Good", "Needs improvement", "Poor"];
  return (
    <div className="mt-3 space-y-1">
      {values.slice(0, 3).map((bin, index) => {
        const percentage = Math.round((bin.density ?? 0) * 100);
        return (
          <div
            key={index}
            className="grid grid-cols-[7rem_1fr_3rem] items-center gap-2 text-xs"
          >
            <span>{labels[index]}</span>
            <span className="h-2 bg-stone-200">
              <span
                className="block h-full bg-sky-600"
                style={{ width: `${percentage}%` }}
              />
            </span>
            <span className="text-right tabular-nums">{percentage}%</span>
          </div>
        );
      })}
    </div>
  );
}

function OriginContext({
  observation,
  metrics,
}: {
  observation: PerformanceObservation;
  metrics: PerformanceMetricPresentation[];
}) {
  return (
    <section className="border-y border-stone-200 py-4">
      <h2 className="font-semibold">Site-origin context</h2>
      <p className="mt-1 break-all font-mono text-xs">
        {observation.requested_target}
      </p>
      <p className="mt-1 text-sm text-stone-600">
        Collected in the same run. Origin evidence describes the Site origin and
        is not Page-specific.
      </p>
      <div className="mt-3">
        <MetricGrid metrics={metrics} />
      </div>
    </section>
  );
}

function AuditList({
  title,
  items,
}: {
  title: string;
  items: Array<{
    audit_id: string;
    title: string;
    description: string | null;
    display_value: string | null;
    savings_ms: number | null;
    savings_bytes: number | null;
  }>;
}) {
  return (
    <section>
      <h2 className="font-semibold">{title}</h2>
      <div className="mt-3 divide-y border-y border-stone-200">
        {items.map((item) => (
          <article key={item.audit_id} className="py-3">
            <div className="flex flex-wrap justify-between gap-2">
              <strong>{item.title}</strong>
              <span className="text-sm tabular-nums">
                {item.display_value ??
                  (item.savings_ms != null
                    ? `${Math.round(item.savings_ms)} ms potential savings`
                    : item.savings_bytes != null
                      ? `${Math.round(item.savings_bytes).toLocaleString()} bytes potential savings`
                      : "")}
              </span>
            </div>
            {item.description ? (
              <p className="mt-1 whitespace-pre-wrap break-words text-sm text-stone-600 [overflow-wrap:anywhere]">
                {item.description}
              </p>
            ) : null}
            <code className="mt-1 block text-xs text-stone-500">
              {item.audit_id}
            </code>
          </article>
        ))}
      </div>
    </section>
  );
}
