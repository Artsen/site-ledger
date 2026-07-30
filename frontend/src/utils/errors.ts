export type DisplayError = {
  message: string;
  detail?: string;
};

export class ApiError extends Error {
  status: number;
  detail?: string;

  constructor(message: string, status: number, detail?: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

export function errorFromResponse(status: number, body: string): ApiError {
  const parsed = parseBackendDetail(body);
  if (status === 404 && parsed.toLowerCase().includes("scan")) return new ApiError("That scan could not be found.", status, body);
  if (status === 404 && parsed.toLowerCase().includes("snapshot")) return new ApiError("That page snapshot could not be found.", status, body);
  if (status === 404 && parsed.toLowerCase().includes("html")) return new ApiError("The stored HTML for this page is not available.", status, body);
  if (status === 422) return new ApiError("Some submitted values are invalid. Review the highlighted fields and try again.", status, body);
  if (status >= 500) return new ApiError("The scanner API returned an unexpected server error.", status, body);
  return new ApiError(parsed || `Request failed with status ${status}.`, status, body);
}

export function displayError(error: unknown): DisplayError {
  if (error instanceof ApiError) return { message: error.message, detail: error.detail };
  if (error instanceof TypeError && error.message === "Failed to fetch") {
    return {
      message: "The scanner API could not be reached. Confirm that the backend is running.",
      detail: error.message
    };
  }
  if (error instanceof Error) return { message: error.message || "Something went wrong.", detail: error.stack };
  return { message: "Something went wrong.", detail: String(error) };
}

function parseBackendDetail(body: string) {
  try {
    const json = JSON.parse(body) as { detail?: unknown };
    if (typeof json.detail === "string") return json.detail;
    if (Array.isArray(json.detail)) return json.detail.map((item) => validationDetail(item)).filter(Boolean).join(" ");
  } catch {
    return body;
  }
  return body;
}

function validationDetail(item: unknown) {
  if (!item || typeof item !== "object") return "";
  const record = item as Record<string, unknown>;
  return typeof record.msg === "string" ? record.msg : "";
}
