import { useQueryClient } from "@tanstack/react-query";

import {
  deleteAccessibilityObservation,
  deleteAccessibilityRun,
  deletePerformanceObservation,
  deletePerformanceRun,
  getAccessibilityObservationDeletePreview,
  getAccessibilityRunDeletePreview,
  getAccessibilitySiteDeletePreview,
  getPerformanceObservationDeletePreview,
  getPerformanceRunDeletePreview,
  getPerformanceSiteDeletePreview,
  purgeAccessibilitySite,
  purgePerformanceSite,
} from "../../api/client";
import type { AccessibilityDeleteResult } from "../../types/accessibility";
import type { PerformanceDeleteResult } from "../../types/performance";
import { DeletionImpact, DestructiveEvidenceAction } from "./DestructiveEvidenceAction";

export type EvidenceDeleteResult = PerformanceDeleteResult | AccessibilityDeleteResult;

function formatBytes(value: number) {
  if (value < 1_024) return `${value} B`;
  if (value < 1_048_576) return `${(value / 1_024).toFixed(1)} KB`;
  return `${(value / 1_048_576).toFixed(1)} MB`;
}

async function invalidateDomain(queryClient: ReturnType<typeof useQueryClient>, domain: "performance" | "accessibility") {
  await queryClient.invalidateQueries({
    predicate: (query) => query.queryKey.some((part) => typeof part === "string" && part.includes(domain)),
  });
}

export function EvidenceDeletionNotice({ result }: { result: EvidenceDeleteResult | null }) {
  if (!result) return null;
  const deleted = result.observations_deleted || result.runs_deleted;
  return <div role="status" className={`rounded-md border p-3 text-sm ${result.warnings.length ? "border-amber-300 bg-amber-50 text-amber-950" : "border-emerald-300 bg-emerald-50 text-emerald-950"}`}><strong>Evidence deleted.</strong> {deleted ? `${deleted.toLocaleString()} record${deleted === 1 ? "" : "s"} removed.` : "Deletion completed."}{result.warnings.length ? <ul className="mt-2 list-disc pl-5">{result.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul> : null}</div>;
}

export function PerformanceObservationDeleteAction({ siteId, observationId, onDeleted }: { siteId: string; observationId: number; onDeleted: (result: PerformanceDeleteResult) => void | Promise<void> }) {
  const queryClient = useQueryClient();
  return <DestructiveEvidenceAction label="Delete observation" title="Delete Performance observation" description="This permanently removes this retained observation and any exclusively referenced raw payload." queryKey={["performance-observation-delete-preview", siteId, observationId]} loadPreview={() => getPerformanceObservationDeletePreview(siteId, observationId)} deleteEvidence={() => deletePerformanceObservation(siteId, observationId)} onDeleted={async (result) => { await invalidateDomain(queryClient, "performance"); await onDeleted(result); }} renderPreview={(preview) => <DeletionImpact items={[{ label: "Provider / dimension", value: `${preview.provider} / ${preview.dimension}` }, { label: "Outcome", value: preview.outcome }, { label: "Payload references", value: preview.payload_reference_count }, { label: "Reclaimable storage", value: formatBytes(preview.stored_bytes_reclaimable) }]} />} />;
}

export function PerformanceRunDeleteAction({ siteId, runId, onDeleted, compact = false }: { siteId: string; runId: number; onDeleted: (result: PerformanceDeleteResult) => void | Promise<void>; compact?: boolean }) {
  const queryClient = useQueryClient();
  const phrase = `DELETE PERFORMANCE RUN ${runId}`;
  return <DestructiveEvidenceAction className={compact ? "min-h-8 px-2 py-1 text-xs" : undefined} label={compact ? "Delete" : "Delete run"} title={`Delete Performance run ${runId}`} description="This permanently removes the run, its retained observations, related job history, and payloads that no other evidence references." queryKey={["performance-run-delete-preview", siteId, runId]} loadPreview={() => getPerformanceRunDeletePreview(siteId, runId)} deleteEvidence={(confirmation) => deletePerformanceRun(siteId, runId, confirmation)} confirmationPhrase={phrase} onDeleted={async (result) => { await invalidateDomain(queryClient, "performance"); await onDeleted(result); }} renderPreview={(preview) => <DeletionImpact items={[{ label: "Collection completed", value: preview.completed_count }, { label: "Retained observations", value: preview.retained_observation_count }, { label: "Already deleted", value: preview.deleted_observation_count }, { label: "Exclusive payloads", value: preview.exclusive_payload_blobs }, { label: "Shared payloads retained", value: preview.shared_payload_blobs }, { label: "Job events", value: preview.job_events_removed }, { label: "Reclaimable storage", value: formatBytes(preview.stored_bytes_reclaimable) }]} />} />;
}

export function PerformanceSiteDeleteAction({ siteId, onDeleted }: { siteId: string; onDeleted: (result: PerformanceDeleteResult) => void | Promise<void> }) {
  const queryClient = useQueryClient();
  return <DestructiveEvidenceAction label="Delete all Performance evidence" title="Delete all Performance evidence" description="This purges only Performance runs, observations, job history, and exclusively referenced payloads for this Site. Pages and Accessibility evidence remain." queryKey={["performance-site-delete-preview", siteId]} loadPreview={() => getPerformanceSiteDeletePreview(siteId)} deleteEvidence={(confirmation) => purgePerformanceSite(siteId, confirmation)} confirmationPhrase="DELETE PERFORMANCE" onDeleted={async (result) => { await invalidateDomain(queryClient, "performance"); await onDeleted(result); }} renderPreview={(preview) => <DeletionImpact items={[{ label: "Runs", value: preview.runs }, { label: "Retained observations", value: preview.retained_observations }, { label: "Already deleted", value: preview.already_deleted_observations }, { label: "Shared payloads retained", value: preview.shared_payload_blobs }, { label: "Job events", value: preview.job_events_removed }, { label: "Reclaimable storage", value: formatBytes(preview.stored_bytes_reclaimable) }]} />} />;
}

export function AccessibilityObservationDeleteAction({ siteId, observationId, onDeleted }: { siteId: string; observationId: number; onDeleted: (result: AccessibilityDeleteResult) => void | Promise<void> }) {
  const queryClient = useQueryClient();
  return <DestructiveEvidenceAction label="Delete observation" title="Delete Accessibility observation" description="This permanently removes this observation, its rules and affected-node evidence, and any exclusively referenced raw payload." queryKey={["accessibility-observation-delete-preview", siteId, observationId]} loadPreview={() => getAccessibilityObservationDeletePreview(siteId, observationId)} deleteEvidence={() => deleteAccessibilityObservation(siteId, observationId)} onDeleted={async (result) => { await invalidateDomain(queryClient, "accessibility"); await onDeleted(result); }} renderPreview={(preview) => <DeletionImpact items={[{ label: "Profile / outcome", value: `${preview.profile} / ${preview.outcome}` }, { label: "Rule rows", value: preview.rule_rows_deleted }, { label: "Node rows", value: preview.node_rows_deleted }, { label: "Payload references", value: preview.payload_reference_count }, { label: "Reclaimable storage", value: formatBytes(preview.stored_bytes_reclaimable) }]} />} />;
}

export function AccessibilityRunDeleteAction({ siteId, runId, onDeleted, compact = false }: { siteId: string; runId: number; onDeleted: (result: AccessibilityDeleteResult) => void | Promise<void>; compact?: boolean }) {
  const queryClient = useQueryClient();
  const phrase = `DELETE ACCESSIBILITY RUN ${runId}`;
  return <DestructiveEvidenceAction className={compact ? "min-h-8 px-2 py-1 text-xs" : undefined} label={compact ? "Delete" : "Delete run"} title={`Delete Accessibility run ${runId}`} description="This permanently removes the run, observations, rule and node evidence, related job history, and unshared payloads." queryKey={["accessibility-run-delete-preview", siteId, runId]} loadPreview={() => getAccessibilityRunDeletePreview(siteId, runId)} deleteEvidence={(confirmation) => deleteAccessibilityRun(siteId, runId, confirmation)} confirmationPhrase={phrase} onDeleted={async (result) => { await invalidateDomain(queryClient, "accessibility"); await onDeleted(result); }} renderPreview={(preview) => <DeletionImpact items={[{ label: "Collection completed", value: preview.completed_count }, { label: "Retained observations", value: preview.retained_observation_count }, { label: "Already deleted", value: preview.deleted_observation_count }, { label: "Rule rows", value: preview.rule_rows_removed }, { label: "Node rows", value: preview.node_rows_removed }, { label: "Shared payloads retained", value: preview.shared_payload_blobs }, { label: "Job events", value: preview.job_events_removed }, { label: "Reclaimable storage", value: formatBytes(preview.stored_bytes_reclaimable) }]} />} />;
}

export function AccessibilitySiteDeleteAction({ siteId, onDeleted }: { siteId: string; onDeleted: (result: AccessibilityDeleteResult) => void | Promise<void> }) {
  const queryClient = useQueryClient();
  return <DestructiveEvidenceAction label="Delete all Accessibility evidence" title="Delete all Accessibility evidence" description="This purges only Accessibility runs, observations, rule and node evidence, job history, and exclusively referenced payloads for this Site. Pages and Performance evidence remain." queryKey={["accessibility-site-delete-preview", siteId]} loadPreview={() => getAccessibilitySiteDeletePreview(siteId)} deleteEvidence={(confirmation) => purgeAccessibilitySite(siteId, confirmation)} confirmationPhrase="DELETE ACCESSIBILITY" onDeleted={async (result) => { await invalidateDomain(queryClient, "accessibility"); await onDeleted(result); }} renderPreview={(preview) => <DeletionImpact items={[{ label: "Runs", value: preview.runs }, { label: "Retained observations", value: preview.retained_observations }, { label: "Rule rows", value: preview.rule_rows_removed }, { label: "Node rows", value: preview.node_rows_removed }, { label: "Shared payloads retained", value: preview.shared_payload_blobs }, { label: "Reclaimable storage", value: formatBytes(preview.stored_bytes_reclaimable) }]} />} />;
}
