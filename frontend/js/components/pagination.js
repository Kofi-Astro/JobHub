/** Pager for the results list. Emits page numbers via `onPage`. */
import { el } from "../util/dom.js";

/**
 * @param {{page:number,total:number,pageSize:number}} state
 * @param {(page:number)=>void} onPage
 */
export function pagination({ page, total, pageSize }, onPage) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  if (pages <= 1) return el("div");

  const btn = (label, target, { disabled = false, current = false } = {}) =>
    el(
      "button",
      {
        type: "button",
        disabled,
        "aria-current": current ? "page" : null,
        class: [
          "min-w-9 rounded-md px-3 py-1.5 text-sm font-medium transition",
          current
            ? "bg-brand-500 text-white"
            : "text-ink-700 hover:bg-slate-100 disabled:opacity-40 disabled:hover:bg-transparent",
        ].join(" "),
        onClick: () => !disabled && !current && onPage(target),
      },
      label,
    );

  // Window of page numbers around the current page.
  const windowed = [];
  const from = Math.max(1, page - 2);
  const to = Math.min(pages, from + 4);
  for (let p = from; p <= to; p++) windowed.push(p);

  return el(
    "nav",
    { class: "mt-6 flex items-center justify-center gap-1", "aria-label": "Pagination" },
    [
      btn("Previous", page - 1, { disabled: page <= 1 }),
      from > 1 && el("span", { class: "px-1 text-ink-400" }, "…"),
      ...windowed.map((p) => btn(String(p), p, { current: p === page })),
      to < pages && el("span", { class: "px-1 text-ink-400" }, "…"),
      btn("Next", page + 1, { disabled: page >= pages }),
    ],
  );
}
