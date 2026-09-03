import type { FindingDetail, FindingEvaluation, FindingEvaluationList, FindingList, FindingResetResult } from "../types/findings";
import { errorFromResponse } from "../utils/errors";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, init);
  if (!response.ok) throw errorFromResponse(response.status, await response.text());
  return response.json() as Promise<T>;
}

export function listFindings(siteId: string | number, query: string) {
  return request<FindingList>(`/api/sites/${siteId}/findings?${query}`);
}

export function getFinding(siteId: string | number, findingId: string | number) {
  return request<FindingDetail>(`/api/sites/${siteId}/findings/${findingId}`);
}

export function listFindingEvaluations(siteId: string | number, query: string) {
  return request<FindingEvaluationList>(`/api/sites/${siteId}/findings/evaluations?${query}`);
}

export function createFindingEvaluation(siteId: string | number) {
  return request<FindingEvaluation>(`/api/sites/${siteId}/findings/evaluations`, { method: "POST" });
}

export function setFindingAcknowledged(siteId: string | number, findingId: string | number, acknowledged: boolean) {
  return request<FindingDetail>(`/api/sites/${siteId}/findings/${findingId}/${acknowledged ? "acknowledge" : "unacknowledge"}`, { method: "POST" });
}

export async function deleteFinding(siteId: string | number, findingId: string | number) {
  const response = await fetch(`${API_BASE}/api/sites/${siteId}/findings/${findingId}`, { method: "DELETE" });
  if (!response.ok) throw errorFromResponse(response.status, await response.text());
}

export function resetSiteFindings(siteId: string | number) {
  return request<FindingResetResult>(`/api/sites/${siteId}/findings/reset`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ confirm: true }),
  });
}
