/**
 * Local persistence for anonymous visitors (brief: "Anonymous users get
 * reasonable state persistence via localStorage").
 *
 * Everything here is per-browser and best-effort — every read/write is wrapped
 * so a private window or disabled storage degrades gracefully. When the user
 * signs in, `auth.js` calls `exportForMerge()` once and POSTs it to
 * `/api/seeker/merge-anon`, then `clearSavedJobs()` so the account API becomes
 * the single source of truth going forward.
 */

const KEYS = {
  savedJobs: "jobhub.saved_jobs", // [{id, title, company, savedAt}]
  lastSearch: "jobhub.last_search", // querystring of the last results view
  filtersOpen: "jobhub.filters_open", // sidebar collapsed state (desktop)
  recentViews: "jobhub.recent_views", // [{id, title, viewedAt}] capped
};

function read(key, fallback) {
  try {
    const raw = localStorage.getItem(key);
    return raw ? JSON.parse(raw) : fallback;
  } catch {
    return fallback;
  }
}

function write(key, value) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    /* storage full or unavailable — ignore */
  }
}

// --- Saved jobs -----------------------------------------------------------

export function getSavedJobs() {
  return read(KEYS.savedJobs, []);
}

/** Called once after a first login folds these into the account (auth.js). */
export function clearSavedJobs() {
  write(KEYS.savedJobs, []);
  window.dispatchEvent(new CustomEvent("savedjobschange"));
}

export function isJobSaved(id) {
  return getSavedJobs().some((j) => j.id === id);
}

/** Toggle a job's saved state. `job` = {id, title, company_name}. */
export function toggleSavedJob(job) {
  const list = getSavedJobs();
  const idx = list.findIndex((j) => j.id === job.id);
  if (idx >= 0) list.splice(idx, 1);
  else list.unshift({ id: job.id, title: job.title, company: job.company_name, savedAt: Date.now() });
  write(KEYS.savedJobs, list.slice(0, 200));
  window.dispatchEvent(new CustomEvent("savedjobschange"));
  return idx < 0; // true if now saved
}

// --- "Resume where you left off" ---------------------------------------

export function setLastSearch(queryString) {
  write(KEYS.lastSearch, queryString);
}
export function getLastSearch() {
  return read(KEYS.lastSearch, null);
}

// --- Filter sidebar collapsed state ----------------------------------

export function getFiltersOpen() {
  return read(KEYS.filtersOpen, true);
}
export function setFiltersOpen(open) {
  write(KEYS.filtersOpen, !!open);
}

// --- Recently viewed --------------------------------------------------

export function recordRecentView(job) {
  const list = read(KEYS.recentViews, []).filter((j) => j.id !== job.id);
  list.unshift({ id: job.id, title: job.title, viewedAt: Date.now() });
  write(KEYS.recentViews, list.slice(0, 30));
}
export function getRecentViews() {
  return read(KEYS.recentViews, []);
}

// --- Merge payload for first sign-in --------------------------------

export function exportForMerge() {
  // "Resume where you left off" already works per-browser via localStorage
  // regardless of login state, so only saved jobs need server-side merging —
  // matches MergeAnonIn on the backend (app/schemas/seeker.py).
  return { saved_job_ids: getSavedJobs().map((j) => j.id) };
}
