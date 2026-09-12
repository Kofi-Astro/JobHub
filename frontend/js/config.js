/**
 * Runtime configuration for the static frontend.
 *
 * The API base URL is read from a <meta name="jobhub:api-base"> tag in the HTML
 * so a deploy only has to change that one line (or the meta can be templated by
 * the host). If it is absent we fall back to same-origin, which is correct when
 * the API and the static site are served together.
 */

/** @returns {string} API base URL with no trailing slash. */
function readApiBase() {
  const meta = document.querySelector('meta[name="jobhub:api-base"]');
  const fromMeta = meta?.getAttribute("content")?.trim();
  const base = fromMeta && fromMeta !== "{{API_BASE_URL}}" ? fromMeta : window.location.origin;
  return base.replace(/\/+$/, "");
}

export const CONFIG = Object.freeze({
  API_BASE: readApiBase(),
  PAGE_SIZE: 20,
  // Debounce (ms) before a keystroke in the search box triggers a request.
  SEARCH_DEBOUNCE_MS: 350,
});
