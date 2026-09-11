/**
 * Thin API client over `fetch`.
 *
 * - Prefixes `CONFIG.API_BASE`.
 * - Sends the anonymous `X-Session-Id` (created once, kept in localStorage) so
 *   the backend can group a visitor's analytics events without a cookie.
 * - Attaches the access token when one is present (set by the auth module, M8).
 * - Throws `ApiError` with the parsed body on non-2xx.
 */
import { CONFIG } from "../config.js";

const SESSION_KEY = "jobhub.session_id";

function sessionId() {
  try {
    let id = localStorage.getItem(SESSION_KEY);
    if (!id) {
      id = crypto.randomUUID();
      localStorage.setItem(SESSION_KEY, id);
    }
    return id;
  } catch {
    return null; // private mode / storage disabled — analytics just won't group
  }
}

export class ApiError extends Error {
  constructor(status, body) {
    super(body?.detail || `Request failed (${status})`);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
  }
}

let accessToken = null;
/** Called by the auth module after login / refresh. */
export function setAccessToken(token) {
  accessToken = token || null;
}

async function request(method, path, { query, body, headers } = {}) {
  const url = new URL(CONFIG.API_BASE + path);
  if (query instanceof URLSearchParams) url.search = query.toString();
  else if (query) url.search = new URLSearchParams(query).toString();

  const sid = sessionId();
  const res = await fetch(url, {
    method,
    headers: {
      ...(body ? { "Content-Type": "application/json" } : {}),
      ...(sid ? { "X-Session-Id": sid } : {}),
      ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
      ...headers,
    },
    body: body ? JSON.stringify(body) : undefined,
    credentials: "include", // refresh-token cookie (M8)
  });

  if (res.status === 204) return null;
  const text = await res.text();
  const data = text ? JSON.parse(text) : null;
  if (!res.ok) throw new ApiError(res.status, data);
  return data;
}

export const api = {
  // --- Jobs / search ---
  listJobs: (params) => request("GET", "/api/jobs", { query: params }),
  facets: (params) => request("GET", "/api/jobs/facets", { query: params }),
  getJob: (id) => request("GET", `/api/jobs/${id}`),
  recordView: (id) => request("POST", `/api/jobs/${id}/view`).catch(() => {}),
  applyClick: (id) => request("POST", `/api/jobs/${id}/apply-click`),

  // --- Taxonomy / meta ---
  taxonomy: () => request("GET", "/api/taxonomy"),
  countries: () => request("GET", "/api/meta/countries"),
  sources: () => request("GET", "/api/meta/sources"),
};

export { request };
