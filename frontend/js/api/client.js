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

/**
 * Build a URLSearchParams from a plain object, DROPPING null/undefined
 * entries rather than stringifying them.
 *
 * `new URLSearchParams({status: undefined})` does NOT omit the key — it
 * coerces the value with `String(undefined)`, sending the literal query
 * string `status=undefined`. Every optional filter in this client is passed
 * as `value || undefined` specifically so it's left out when unset, so this
 * omission has to happen here or every one of those endpoints 422s on
 * FastAPI's query-type validation the moment a caller leaves a filter blank.
 */
function cleanParams(obj) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(obj)) {
    if (value == null) continue;
    params.set(key, value);
  }
  return params;
}

async function request(method, path, { query, body, headers } = {}) {
  const url = new URL(CONFIG.API_BASE + path);
  if (query instanceof URLSearchParams) url.search = query.toString();
  else if (query) url.search = cleanParams(query).toString();

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

  // --- Auth ---
  registerSeeker: (body) => request("POST", "/api/auth/register/seeker", { body }),
  registerEmployer: (body) => request("POST", "/api/auth/register/employer", { body }),
  login: (body) => request("POST", "/api/auth/login", { body }),
  refresh: () => request("POST", "/api/auth/refresh"),
  logout: () => request("POST", "/api/auth/logout"),
  me: () => request("GET", "/api/auth/me"),

  // --- Seeker account ---
  savedJobs: () => request("GET", "/api/seeker/saved-jobs"),
  saveJob: (jobId, notes) => request("POST", "/api/seeker/saved-jobs", { body: { job_id: jobId, notes } }),
  unsaveJob: (jobId) => request("DELETE", `/api/seeker/saved-jobs/${jobId}`),
  savedSearches: () => request("GET", "/api/seeker/saved-searches"),
  createSavedSearch: (body) => request("POST", "/api/seeker/saved-searches", { body }),
  updateSavedSearch: (id, body) => request("PATCH", `/api/seeker/saved-searches/${id}`, { body }),
  deleteSavedSearch: (id) => request("DELETE", `/api/seeker/saved-searches/${id}`),
  mergeAnon: (body) => request("POST", "/api/seeker/merge-anon", { body }),

  // --- Employer portal ---
  postJob: (body) => request("POST", "/api/employer/jobs", { body }),
  employerJobs: () => request("GET", "/api/employer/jobs"),
  getEmployerJob: (id) => request("GET", `/api/employer/jobs/${id}`),
  updateEmployerJob: (id, body) => request("PATCH", `/api/employer/jobs/${id}`, { body }),
  closeJob: (id) => request("POST", `/api/employer/jobs/${id}/close`),
  republishJob: (id) => request("POST", `/api/employer/jobs/${id}/republish`),
  employerStats: () => request("GET", "/api/employer/stats"),

  // --- Admin: employer + job moderation ---
  adminPendingEmployers: () => request("GET", "/api/admin/employers/pending"),
  adminApproveEmployer: (userId) => request("POST", `/api/admin/employers/${userId}/approve`),
  adminRejectEmployer: (userId, reason) => request("POST", `/api/admin/employers/${userId}/reject`, { body: { reason } }),
  adminPendingJobs: () => request("GET", "/api/admin/jobs/pending"),
  adminApproveJob: (jobId) => request("POST", `/api/admin/jobs/${jobId}/approve`),
  adminRejectJob: (jobId, reason) => request("POST", `/api/admin/jobs/${jobId}/reject`, { body: { reason } }),

  // --- Admin: taxonomy ---
  adminTaxonomy: () => request("GET", "/api/admin/taxonomy"),
  adminCreateField: (body) => request("POST", "/api/admin/taxonomy/fields", { body }),
  adminUpdateField: (id, body) => request("PATCH", `/api/admin/taxonomy/fields/${id}`, { body }),
  adminDeleteField: (id) => request("DELETE", `/api/admin/taxonomy/fields/${id}`),
  adminCreateSubfield: (body) => request("POST", "/api/admin/taxonomy/subfields", { body }),
  adminUpdateSubfield: (id, body) => request("PATCH", `/api/admin/taxonomy/subfields/${id}`, { body }),
  adminDeleteSubfield: (id) => request("DELETE", `/api/admin/taxonomy/subfields/${id}`),
  adminRemapSubfield: (id, targetId) => request("POST", `/api/admin/taxonomy/subfields/${id}/remap`, { body: { target_subfield_id: targetId } }),
  adminUncategorized: (params) => request("GET", "/api/admin/taxonomy/uncategorized", { query: params }),
  adminCategorizeJob: (jobId, body) => request("POST", `/api/admin/jobs/${jobId}/categorize`, { body }),

  // --- Admin: sources ---
  adminSources: () => request("GET", "/api/admin/sources"),
  adminCreateSource: (body) => request("POST", "/api/admin/sources", { body }),
  adminUpdateSource: (id, body) => request("PATCH", `/api/admin/sources/${id}`, { body }),
  adminSourceRuns: (id) => request("GET", `/api/admin/sources/${id}/runs`),
  adminRunSourceNow: (id) => request("POST", `/api/admin/sources/${id}/run-now`),

  // --- Admin: general job management ---
  adminListJobs: (params) => request("GET", "/api/admin/jobs", { query: params }),
  adminUpdateJob: (id, body) => request("PATCH", `/api/admin/jobs/${id}`, { body }),
  adminHideJob: (id) => request("POST", `/api/admin/jobs/${id}/hide`),
  adminUnhideJob: (id) => request("POST", `/api/admin/jobs/${id}/unhide`),

  // --- Admin: users ---
  adminListUsers: (params) => request("GET", "/api/admin/users", { query: params }),
  adminDisableUser: (id) => request("POST", `/api/admin/users/${id}/disable`),
  adminEnableUser: (id) => request("POST", `/api/admin/users/${id}/enable`),
  adminResetPassword: (id) => request("POST", `/api/admin/users/${id}/reset-password`),
  adminListAdmins: () => request("GET", "/api/admin/users/admins"),
  adminCreateAdmin: (body) => request("POST", "/api/admin/users/admins", { body }),

  // --- Admin: content ---
  adminListContent: () => request("GET", "/api/admin/content"),
  adminSetContent: (key, value) => request("PUT", `/api/admin/content/${key}`, { body: { value } }),
  adminListAnnouncements: () => request("GET", "/api/admin/announcements"),
  adminCreateAnnouncement: (body) => request("POST", "/api/admin/announcements", { body }),
  adminUpdateAnnouncement: (id, body) => request("PATCH", `/api/admin/announcements/${id}`, { body }),
  adminDeleteAnnouncement: (id) => request("DELETE", `/api/admin/announcements/${id}`),
  activeAnnouncement: () => request("GET", "/api/announcements/active"),

  // --- Admin: analytics ---
  adminAnalyticsSummary: (periodDays) => request("GET", "/api/admin/analytics/summary", { query: { period_days: periodDays } }),
};

export { request };
