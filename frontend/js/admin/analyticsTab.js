/**
 * Analytics tab: traffic, top searches, jobs per source, employer activity
 * (brief: "basic analytics dashboard").
 */
import { el, mount } from "../util/dom.js";
import { api } from "../api/client.js";
import { sectionTitle, errorNote } from "./shared.js";

export async function renderAnalytics(root) {
  mount(root, []);
  const periodSelect = el(
    "select",
    { class: "rounded-lg border border-slate-300 px-2 py-1.5 text-sm" },
    [
      ["7", "Last 7 days"],
      ["30", "Last 30 days"],
      ["90", "Last 90 days"],
    ].map(([v, label]) => el("option", { value: v }, label)),
  );
  periodSelect.value = "30";
  const body = el("div", { class: "mt-4" });
  root.append(sectionTitle("Analytics"), periodSelect, body);
  periodSelect.addEventListener("change", load);

  async function load() {
    try {
      const s = await api.adminAnalyticsSummary(Number(periodSelect.value));
      mount(body, [
        el("div", { class: "grid grid-cols-2 gap-3 sm:grid-cols-4" }, [
          tile("Page views", s.page_views),
          tile("Searches", s.searches),
          tile("Job views", s.job_views),
          tile("Apply clicks", s.apply_clicks),
          tile("Seeker signups", s.seeker_signups),
          tile("Employer signups", s.employer_signups),
          tile("Jobs posted by employers", s.jobs_posted_by_employers),
        ]),
        el("div", { class: "mt-6 grid gap-6 sm:grid-cols-2" }, [
          listBlock("Top searches", s.top_searches.map((r) => `${r.q} (${r.count})`)),
          listBlock("Jobs per source", s.jobs_per_source.map((r) => `${r.source}: ${r.count}`)),
        ]),
      ]);
    } catch (err) {
      mount(body, errorNote(err));
    }
  }

  await load();
}

function tile(label, value) {
  return el("div", { class: "rounded-card border border-slate-200 bg-white p-4 text-center" }, [
    el("div", { class: "text-2xl font-bold text-ink-900" }, String(value)),
    el("div", { class: "text-xs text-ink-500" }, label),
  ]);
}

function listBlock(title, items) {
  return el("div", { class: "rounded-card border border-slate-200 bg-white p-4" }, [
    el("h3", { class: "mb-2 font-semibold text-ink-800" }, title),
    items.length
      ? el("ul", { class: "space-y-1 text-sm text-ink-700" }, items.map((i) => el("li", {}, i)))
      : el("p", { class: "text-sm text-ink-400" }, "No data yet."),
  ]);
}
