import { useQueryClient } from "@tanstack/react-query";

import {
  deleteLegacyRenderedObservations,
  deleteRenderedObservation,
  deleteRenderRun,
  deleteRenderTargetEvidence,
  getLegacyRenderedDeletionPreview,
  getRenderedObservationDeletionPreview,
  getRenderRunDeletionPreview,
  getRenderTargetDeletionPreview,
  getScanRenderedDeletionPreview,
  getSiteRenderedDeletionPreview,
  purgeScanRenderedEvidence,
  purgeSiteRenderedEvidence,
} from "../../api/client";
import type { RenderDeleteImpact, RenderDeleteResult } from "../../types/scans";
import { DeletionImpact, DestructiveEvidenceAction } from "../observability/DestructiveEvidenceAction";

function formatBytes(value: number) {
  if (value < 1_024) return `${value} B`;
  if (value < 1_048_576) return `${(value / 1_024).toFixed(1)} KB`;
  return `${(value / 1_048_576).toFixed(1)} MB`;
}

function Impact({ value }: { value: RenderDeleteImpact }) {
  return <DeletionImpact items={[
    { label: "Retained observations", value: value.observations },
    { label: "Targets without evidence", value: value.targets_already_without_evidence },
    { label: "Browser detail rows", value: value.network_rows + value.console_rows + value.page_error_rows },
    { label: "Artifacts", value: value.artifact_rows },
    { label: "Shared artifacts retained", value: value.shared_artifact_blobs_retained },
    { label: "Reclaimable storage", value: formatBytes(value.stored_bytes_reclaimable) },
    { label: "Job events", value: value.job_events },
    { label: "Rerender links detached", value: value.child_rerender_links_detached },
  ]} />;
}

async function invalidateRendered(queryClient: ReturnType<typeof useQueryClient>) {
  await queryClient.invalidateQueries({
    predicate: (query) => query.queryKey.some((part) => {
      const value = String(part);
      return value.includes("render") || value === "scan";
    }),
  });
}

type Complete = (result: RenderDeleteResult) => void | Promise<void>;

export function RenderObservationDeleteAction({ siteId, observationId, onDeleted }: { siteId: string; observationId: string; onDeleted: Complete }) {
  const queryClient = useQueryClient();
  return <DestructiveEvidenceAction label="Delete observation" title="Delete rendered observation" description="This removes retained browser evidence and exclusively referenced artifacts. The Page, Scan, and static evidence remain." queryKey={["rendered-observation-delete-preview", siteId, observationId]} loadPreview={() => getRenderedObservationDeletionPreview(siteId, observationId)} deleteEvidence={() => deleteRenderedObservation(siteId, observationId)} onDeleted={async (result) => { await invalidateRendered(queryClient); await onDeleted(result); }} renderPreview={(preview) => <Impact value={preview} />} />;
}

export function RenderTargetBulkDeleteAction({ siteId, runId, targetIds, onDeleted }: { siteId: string; runId: string; targetIds: number[]; onDeleted: Complete }) {
  const queryClient = useQueryClient();
  return <DestructiveEvidenceAction label={`Delete evidence (${targetIds.length})`} title="Delete selected rendered evidence" description="Only retained browser observations are removed. Frozen Run targets remain and can be rerendered." queryKey={["render-target-delete-preview", siteId, runId, ...targetIds]} loadPreview={() => getRenderTargetDeletionPreview(siteId, runId, targetIds)} deleteEvidence={() => deleteRenderTargetEvidence(siteId, runId, targetIds)} onDeleted={async (result) => { await invalidateRendered(queryClient); await onDeleted(result); }} renderPreview={(preview) => <Impact value={preview} />} />;
}

export function RenderRunDeleteAction({ siteId, runId, onDeleted, compact = false }: { siteId: string; runId: number; onDeleted: Complete; compact?: boolean }) {
  const queryClient = useQueryClient();
  const phrase = `DELETE RENDER RUN ${runId}`;
  return <DestructiveEvidenceAction className={compact ? "min-h-8 px-2 py-1 text-xs" : undefined} label={compact ? "Delete" : "Delete run"} title={`Delete Render Run ${runId}`} description="This removes the Run, targets, browser observations, job history, and unshared artifacts. Pages and Scans remain." queryKey={["render-run-delete-preview", siteId, runId]} loadPreview={() => getRenderRunDeletionPreview(siteId, String(runId))} deleteEvidence={(confirmation) => deleteRenderRun(siteId, String(runId), confirmation)} confirmationPhrase={phrase} onDeleted={async (result) => { await invalidateRendered(queryClient); await onDeleted(result); }} renderPreview={(preview) => <Impact value={preview} />} />;
}

export function RenderSiteDeleteAction({ siteId, onDeleted }: { siteId: string; onDeleted: Complete }) {
  const queryClient = useQueryClient();
  return <DestructiveEvidenceAction label="Delete all Rendered evidence" title="Delete all Rendered evidence" description="This removes Site-owned Render Runs and legacy browser evidence. Pages, Scans, Performance, Accessibility, notes, and categories remain." queryKey={["render-site-delete-preview", siteId]} loadPreview={() => getSiteRenderedDeletionPreview(siteId)} deleteEvidence={(confirmation) => purgeSiteRenderedEvidence(siteId, confirmation)} confirmationPhrase="DELETE RENDERED EVIDENCE" onDeleted={async (result) => { await invalidateRendered(queryClient); await onDeleted(result); }} renderPreview={(preview) => <Impact value={preview} />} />;
}

export function RenderScanDeleteAction({ scanId, onDeleted }: { scanId: string; onDeleted: Complete }) {
  const queryClient = useQueryClient();
  const phrase = `DELETE SCAN RENDERS ${scanId}`;
  return <DestructiveEvidenceAction label="Delete Scan rendered evidence" title="Delete Scan rendered evidence" description="This removes legacy browser evidence and Site-less ad-hoc Render Runs owned by this Scan. Static Scan evidence remains." queryKey={["render-scan-delete-preview", scanId]} loadPreview={() => getScanRenderedDeletionPreview(scanId)} deleteEvidence={(confirmation) => purgeScanRenderedEvidence(scanId, confirmation)} confirmationPhrase={phrase} onDeleted={async (result) => { await invalidateRendered(queryClient); await onDeleted(result); }} renderPreview={(preview) => <Impact value={preview} />} />;
}

export function LegacyRenderBulkDeleteAction({ scanId, observationIds, onDeleted }: { scanId: string; observationIds: number[]; onDeleted: Complete }) {
  const queryClient = useQueryClient();
  return <DestructiveEvidenceAction label={`Delete selected evidence (${observationIds.length})`} title="Delete selected legacy rendered evidence" description="This removes only the selected Scan-bound browser observations and unshared artifacts." queryKey={["legacy-render-delete-preview", scanId, ...observationIds]} loadPreview={() => getLegacyRenderedDeletionPreview(scanId, observationIds)} deleteEvidence={() => deleteLegacyRenderedObservations(scanId, observationIds)} onDeleted={async (result) => { await invalidateRendered(queryClient); await onDeleted(result); }} renderPreview={(preview) => <Impact value={preview} />} />;
}
