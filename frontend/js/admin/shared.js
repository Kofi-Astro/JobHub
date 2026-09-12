/**
 * Small shared helpers for the admin tab modules — a plain table builder and
 * a couple of common bits (status pill, confirm-then-run) so each tab stays
 * focused on its own data instead of re-deriving table markup.
 */
import { el } from "../util/dom.js";

/**
 * @param {string[]} headers
 * @param {any[]} rows
 * @param {(row:any)=>Array<Node|string>} renderRow - cell contents, in header order
 */
export function table(headers, rows, renderRow) {
  if (!rows.length) {
    return el("p", { class: "py-6 text-center text-sm text-ink-500" }, "Nothing here yet.");
  }
  return el("div", { class: "overflow-x-auto rounded-card border border-slate-200 bg-white" }, [
    el("table", { class: "w-full text-left text-sm" }, [
      el(
        "thead",
        { class: "border-b border-slate-200 bg-slate-50 text-xs uppercase tracking-wide text-ink-500" },
        [el("tr", {}, headers.map((h) => el("th", { class: "px-3 py-2 font-semibold" }, h)))],
      ),
      el(
        "tbody",
        { class: "divide-y divide-slate-100" },
        rows.map((row) =>
          el(
            "tr",
            { class: "hover:bg-slate-50" },
            renderRow(row).map((cell) => el("td", { class: "px-3 py-2 align-top" }, cell)),
          ),
        ),
      ),
    ]),
  ]);
}

const PILL_COLOR = {
  active: "bg-emerald-50 text-emerald-700",
  approved: "bg-emerald-50 text-emerald-700",
  pending: "bg-amber-50 text-amber-700",
  rejected: "bg-red-50 text-red-700",
  hidden: "bg-slate-100 text-ink-600",
  closed: "bg-slate-100 text-ink-600",
  expired: "bg-slate-100 text-ink-600",
  suspended: "bg-red-50 text-red-700",
};

export function pill(value) {
  const cls = PILL_COLOR[value] || "bg-slate-100 text-ink-600";
  return el("span", { class: `inline-block rounded-full px-2 py-0.5 text-xs font-medium ${cls}` }, value);
}

export function actionBtn(label, onClick, { danger = false } = {}) {
  return el(
    "button",
    {
      type: "button",
      class: `mr-2 rounded-md px-2 py-1 text-xs font-medium ${
        danger ? "bg-red-50 text-red-700 hover:bg-red-100" : "bg-slate-100 text-ink-700 hover:bg-slate-200"
      }`,
      onClick: async (e) => {
        const btn = e.currentTarget;
        btn.disabled = true;
        try {
          await onClick();
        } finally {
          btn.disabled = false;
        }
      },
    },
    label,
  );
}

/** window.prompt-based reason capture for reject actions — good enough for
 * an internal admin tool; a styled modal is a natural later upgrade. */
export function promptReason(message) {
  const reason = window.prompt(message);
  return reason && reason.trim() ? reason.trim() : null;
}

export function sectionTitle(text) {
  return el("h2", { class: "mb-3 text-lg font-bold text-ink-900" }, text);
}

export function errorNote(err) {
  return el("p", { class: "rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700" }, err?.message || String(err));
}
