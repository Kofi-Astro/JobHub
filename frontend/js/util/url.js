/**
 * Filter state <-> URL query string.
 *
 * The URL is the single source of truth for "what is the user looking at":
 * shareable, bookmarkable, and back/forward works for free. `readFilters()`
 * parses the current URL into a plain object; `writeFilters()` pushes a new
 * state. The same object shape is what we POST when saving a search (M9).
 */

/** Keys that hold multiple values (repeated query params). */
const MULTI = new Set([
  "field",
  "subfield",
  "country",
  "workplace",
  "job_type",
  "experience",
  "source",
]);

/** Keys that are booleans. */
const BOOL = new Set(["remote", "employer_only", "include_undisclosed_salary", "visa_sponsorship"]);

/** Keys that are integers. */
const INT = new Set(["salary_min", "salary_max", "posted_within_days", "page"]);

/**
 * @returns {Record<string, any>} current filter state from `location.search`.
 */
export function readFilters() {
  const params = new URLSearchParams(window.location.search);
  const out = {};
  for (const key of new Set(params.keys())) {
    if (MULTI.has(key)) out[key] = params.getAll(key).filter(Boolean);
    else if (BOOL.has(key)) out[key] = params.get(key) === "true";
    else if (INT.has(key)) out[key] = Number(params.get(key)) || undefined;
    else out[key] = params.get(key) || undefined;
  }
  out.page = out.page || 1;
  return out;
}

/**
 * Serialize a filter object to a URLSearchParams (drops empty values).
 * @param {Record<string, any>} filters
 */
export function toParams(filters) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters || {})) {
    if (value == null || value === "" || value === false) continue;
    if (Array.isArray(value)) {
      if (!value.length) continue;
      for (const v of value) params.append(key, v);
    } else if (key === "page" && Number(value) <= 1) {
      continue; // keep page 1 out of the URL for tidiness
    } else {
      params.set(key, String(value));
    }
  }
  return params;
}

/**
 * Push a new filter state into history and notify listeners.
 * @param {Record<string, any>} filters
 * @param {{replace?: boolean}} [opts]
 */
export function writeFilters(filters, opts = {}) {
  const qs = toParams(filters).toString();
  const url = qs ? `?${qs}` : window.location.pathname;
  if (opts.replace) window.history.replaceState(filters, "", url);
  else window.history.pushState(filters, "", url);
  window.dispatchEvent(new CustomEvent("filterschange", { detail: filters }));
}

/** Toggle one value inside a multi-value key and return the new array. */
export function toggleMulti(current, value) {
  const set = new Set(current || []);
  set.has(value) ? set.delete(value) : set.add(value);
  return [...set];
}
