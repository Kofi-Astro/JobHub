/**
 * Search / results page controller (index.html).
 *
 * Flow:
 *   1. Load reference data once (taxonomy, countries, sources).
 *   2. Read filter state from the URL.
 *   3. Fetch jobs + facets in parallel; render results + sidebar + chips.
 *   4. Any control change → write new state to the URL → step 3 again.
 *      Browser back/forward also re-runs step 3 (popstate).
 *
 * The URL is the state; this module holds only caches + DOM refs.
 */
import { api } from "../api/client.js";
import { CONFIG } from "../config.js";
import { el, mount } from "../util/dom.js";
import { readFilters, toParams, writeFilters } from "../util/url.js";
import { setLastSearch } from "../store/state.js";
import { jobCard } from "../components/jobCard.js";
import { skeletonList } from "../components/skeleton.js";
import { pagination } from "../components/pagination.js";
import { filterSidebar } from "../components/filterSidebar.js";
import { activeFilters } from "../components/activeFilters.js";
import { searchBar } from "../components/searchBar.js";

let refs = { taxonomy: null, countries: [], sources: [] };
let dom = {};
let reqToken = 0; // guards against out-of-order responses

export async function initSearchPage() {
  dom = {
    sidebar: document.getElementById("filter-sidebar"),
    sidebarSheet: document.getElementById("filter-sheet-body"),
    results: document.getElementById("results"),
    resultsMeta: document.getElementById("results-meta"),
    chips: document.getElementById("active-filters"),
    searchMount: document.getElementById("search-bar"),
    sort: document.getElementById("sort-select"),
    filterToggle: document.getElementById("filter-toggle"),
    sheet: document.getElementById("filter-sheet"),
    sheetClose: document.getElementById("filter-sheet-close"),
  };

  // Compact search bar in the results header.
  const renderSearch = () =>
    mount(
      dom.searchMount,
      searchBar({
        value: readFilters().q || "",
        size: "compact",
        onSearch: (q) => update({ ...readFilters(), q: q || undefined, page: 1 }),
      }),
    );
  renderSearch();

  dom.sort.value = readFilters().sort || "relevance";
  dom.sort.addEventListener("change", () =>
    update({ ...readFilters(), sort: dom.sort.value, page: 1 }),
  );

  // Mobile bottom-sheet open/close.
  dom.filterToggle?.addEventListener("click", () => dom.sheet.classList.remove("hidden"));
  dom.sheetClose?.addEventListener("click", () => dom.sheet.classList.add("hidden"));
  dom.sheet?.addEventListener("click", (e) => {
    if (e.target === dom.sheet) dom.sheet.classList.add("hidden");
  });

  // Re-render on back/forward and on any writeFilters() call.
  window.addEventListener("popstate", () => {
    renderSearch();
    load();
  });
  window.addEventListener("filterschange", load);

  // Reference data (best-effort; the page still works if one fails).
  const [taxonomy, countries, sources] = await Promise.allSettled([
    api.taxonomy(),
    api.countries(),
    api.sources(),
  ]);
  refs = {
    taxonomy: taxonomy.value || { fields: [] },
    countries: countries.value || [],
    sources: sources.value || [],
  };

  await load();
}

/** Write a new filter state to the URL (which triggers `load`). */
function update(next) {
  writeFilters(pruneEmpty(next));
}

async function load() {
  const filters = readFilters();
  const params = toParams({ ...filters, page_size: CONFIG.PAGE_SIZE });
  const token = ++reqToken;

  // Show skeletons immediately; keep the sidebar as-is until facets return.
  mount(dom.results, skeletonList(6));
  dom.resultsMeta.textContent = "Searching…";
  setLastSearch(window.location.search);

  const [jobsRes, facetsRes] = await Promise.allSettled([
    api.listJobs(params),
    api.facets(params),
  ]);
  if (token !== reqToken) return; // a newer request already rendered

  const facets = facetsRes.value || null;
  renderSidebar(filters, facets);
  mount(dom.chips, activeFilters(filters, refs, update));

  if (jobsRes.status !== "fulfilled") {
    dom.resultsMeta.textContent = "";
    mount(dom.results, errorState());
    return;
  }

  const page = jobsRes.value;
  dom.resultsMeta.textContent = summaryText(page);

  if (!page.items.length) {
    mount(dom.results, emptyState(filters));
    return;
  }
  mount(dom.results, [
    ...page.items.map((j) => jobCard(j)),
    pagination(
      { page: page.page, total: page.total, pageSize: page.page_size },
      (p) => {
        update({ ...readFilters(), page: p });
        window.scrollTo({ top: 0, behavior: "smooth" });
      },
    ),
  ]);
}

function renderSidebar(filters, facets) {
  const build = (host) =>
    mount(
      host,
      filterSidebar({
        filters,
        facets,
        taxonomy: refs.taxonomy,
        countries: refs.countries,
        sources: refs.sources,
        onChange: (next) => {
          update(next);
          dom.sheet?.classList.add("hidden");
        },
      }),
    );
  if (dom.sidebar) build(dom.sidebar);
  if (dom.sidebarSheet) build(dom.sidebarSheet);
}

// --- small views ---------------------------------------------------

function summaryText(page) {
  const start = (page.page - 1) * page.page_size + 1;
  const end = Math.min(page.total, page.page * page.page_size);
  if (!page.total) return "No jobs found";
  return `${start.toLocaleString()}–${end.toLocaleString()} of ${page.total.toLocaleString()} jobs`;
}

function emptyState(filters) {
  return el("div", { class: "rounded-card border border-dashed border-slate-300 p-10 text-center" }, [
    el("p", { class: "text-lg font-semibold text-ink-800" }, "No jobs match these filters"),
    el("p", { class: "mt-1 text-sm text-ink-500" }, "Try removing a filter or widening your search."),
    filters && el(
      "button",
      {
        type: "button",
        class: "btn-ghost mt-4",
        onClick: () => writeFilters({ q: filters.q }),
      },
      "Clear all filters",
    ),
  ]);
}

function errorState() {
  return el("div", { class: "rounded-card border border-red-200 bg-red-50 p-10 text-center" }, [
    el("p", { class: "font-semibold text-red-800" }, "Couldn't load jobs"),
    el("p", { class: "mt-1 text-sm text-red-600" }, "The server may be starting up. Retry in a moment."),
    el("button", { type: "button", class: "btn-ghost mt-4", onClick: load }, "Retry"),
  ]);
}

function pruneEmpty(obj) {
  const out = {};
  for (const [k, v] of Object.entries(obj)) {
    if (v == null || v === "" || v === false) continue;
    if (Array.isArray(v) && !v.length) continue;
    out[k] = v;
  }
  return out;
}
