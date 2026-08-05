export type Job = {
  id: number;
  job_type: string;
  status: string;
  presentation_status: string;
  priority: number;
  scan_id: number | null;
  source_refresh_id: number | null;
  website_property_id: number | null;
  dedupe_key: string;
  payload_json: Record<string, unknown>;
  progress_version: number;
  progress_json: Record<string, unknown>;
  current_operation: string | null;
  progress_current: number | null;
  progress_total: number | null;
  progress_unit: string | null;
  result_json: Record<string, unknown> | null;
  created_at: string;
  available_at: string;
  claimed_at: string | null;
  started_at: string | null;
  heartbeat_at: string | null;
  lease_expires_at: string | null;
  finished_at: string | null;
  worker_id: string | null;
  attempt_count: number;
  max_attempts: number;
  cancellation_requested_at: string | null;
  cancelled_at: string | null;
  error_type: string | null;
  error_message: string | null;
  last_error_at: string | null;
};

export type JobList = {
  items: Job[];
  total: number;
  limit: number;
  offset: number;
};

export type WorkerHealth = {
  online_workers: number;
  total_concurrency: number;
  last_worker_heartbeat: string | null;
  queued_work_has_worker: boolean;
  offline_threshold_seconds: number;
};
