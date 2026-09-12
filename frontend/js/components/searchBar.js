/**
 * Search input. Two visual sizes ("hero" on the homepage top, "compact" in the
 * results header) but the same behaviour: debounced typing updates the query,
 * Enter submits immediately.
 */
import { el, icons, debounce } from "../util/dom.js";
import { CONFIG } from "../config.js";

/**
 * @param {{value?:string, size?:"hero"|"compact", onSearch:(q:string)=>void}} opts
 */
export function searchBar({ value = "", size = "compact", onSearch }) {
  const hero = size === "hero";
  const fire = debounce((q) => onSearch(q), CONFIG.SEARCH_DEBOUNCE_MS);

  const input = el("input", {
    type: "search",
    value,
    placeholder: "Job title, skill, or company",
    "aria-label": "Search jobs",
    class: [
      "w-full bg-transparent outline-none placeholder:text-ink-400",
      hero ? "text-lg" : "text-sm",
    ].join(" "),
    onInput: (e) => fire(e.target.value.trim()),
    onKeydown: (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        onSearch(e.target.value.trim());
      }
    },
  });

  return el(
    "form",
    {
      role: "search",
      class: [
        "flex items-center gap-2 rounded-xl border bg-white",
        hero ? "border-slate-300 px-4 py-3 shadow-card" : "border-slate-300 px-3 py-2",
      ].join(" "),
      onSubmit: (e) => {
        e.preventDefault();
        onSearch(input.value.trim());
      },
    },
    [
      el("span", { class: "text-ink-400", html: icons.search }),
      input,
      hero &&
        el("button", { type: "submit", class: "btn-primary shrink-0" }, "Search"),
    ],
  );
}
