import type { CollectionPlan, CollectionPlanList, CollectionPlanPreview, CollectionPlanRequest } from "../types/collectionPlans";
import { errorFromResponse } from "../utils/errors";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!response.ok) throw errorFromResponse(response.status, await response.text());
  return response.json() as Promise<T>;
}

export const previewCollectionPlan = (siteId: string | number, payload: CollectionPlanRequest) =>
  request<CollectionPlanPreview>(`/api/sites/${siteId}/collection-plans/preview?limit=20`, { method: "POST", body: JSON.stringify(payload) });

export const createCollectionPlan = (siteId: string | number, payload: CollectionPlanRequest) =>
  request<CollectionPlan>(`/api/sites/${siteId}/collection-plans`, { method: "POST", body: JSON.stringify(payload) });

export const listCollectionPlans = (siteId: string | number, query = "") =>
  request<CollectionPlanList>(`/api/sites/${siteId}/collection-plans${query}`);

export const getCollectionPlan = (siteId: string | number, planId: string | number) =>
  request<CollectionPlan>(`/api/sites/${siteId}/collection-plans/${planId}`);

export const cancelCollectionPlan = (siteId: string | number, planId: string | number) =>
  request<CollectionPlan>(`/api/sites/${siteId}/collection-plans/${planId}/cancel`, { method: "POST" });
