/**
 * Sources tab: the adapter registry — enable/disable, tier, rate limit,
 * refresh interval, run-now, and recent run history (brief: "manage sources —
 * add/edit/disable, tier/free-vs-paid, API keys, rate limits, sync health").
 */
import { el, mount } from "../util/dom.js";
import { api, ApiError } from "../api/client.js";
import { pill, actionBtn, sectionTitle, errorNote } from "./shared.js";

export async function renderSources(root) {
  mount(root, [sectionTitle("Sources")]);
  const listSlot = el("div", { class: "space-y-3" });
  root.append(listSlot);

  async function load() {
    try {
      const sources = await api.adminSources();
      mount(listSlot, sources.map((s) => sourceRow(s, load)));
    } catch (err) {
      mount(listSlot, errorNote(err));
    }
  }
  await load();
}

function sourceRow(source, reload) {
  const errorLine = source.last_error
    ? el("p", { class: "mt-1 text-xs text-red-600" }, `Last error: ${source.last_error}`)
    : null;

  const runsSlot = el("div", { class: "mt-2 hidden" });
  const toggleRuns = actionBtn("History", async () => {
    if (!runsSlot.classList.contains("hidden")) {
      runsSlot.classList.add("hidden");
      return;
    }
    const runs = await api.adminSourceRuns(source.id);
    mount(
      runsSlot,
      el(
        "ul",
        { class: "space-y-1 rounded bg-slate-50 p-2 text-xs" },
        runs.map((r) =>
          el("li", {}, `${new Date(r.started_at).toLocaleString()} — ${r.status} (+${r.jobs_created} ~${r.jobs_updated} -${r.jobs_expired} !${r.jobs_failed})`),
        ),
      ),
    );
    runsSlot.classList.remove("hidden");
  });

  const runNowBtn = actionBtn("Run now", async () => {
    try {
      await api.adminRunSourceNow(source.id);
      reload();
    } catch (err) {
      window.alert(err instanceof ApiError ? err.message : "Failed to run.");
    }
  });

  const toggleBtn = actionBtn(source.enabled ? "Disable" : "Enable", async () => {
    try {
      await api.adminUpdateSource(source.id, { enabled: !source.enabled });
      reload();
    } catch (err) {
      window.alert(err instanceof ApiError ? err.message : "Update failed.");
    }
  });

  const editBtn = actionBtn("Edit limits", async () => {
    const rate = window.prompt("Rate limit per minute (blank = unlimited):", source.rate_limit_per_min ?? "");
    if (rate === null) return;
    const interval = window.prompt("Refresh interval, minutes:", source.refresh_interval_minutes);
    if (interval === null) return;
    await api.adminUpdateSource(source.id, {
      rate_limit_per_min: rate === "" ? null : Number(rate),
      refresh_interval_minutes: Number(interval),
    });
    reload();
  });

  return el("div", { class: "job-card" }, [
    el("div", { class: "flex flex-wrap items-center justify-between gap-2" }, [
      el("div", {}, [
        el("span", { class: "font-semibold text-ink-900" }, source.name),
        el("span", { class: "ml-2 text-xs text-ink-400" }, `${source.kind} · ${source.tier}${source.requires_api_key ? " · keyed" : ""}`),
      ]),
      el("span", { class: "flex items-center gap-2" }, [
        pill(source.enabled ? "active" : "hidden"),
        `${source.job_count} jobs`,
      ]),
    ]),
    el("p", { class: "mt-1 text-xs text-ink-500" }, [
      `Last run: ${source.last_run_at ? new Date(source.last_run_at).toLocaleString() : "never"}`,
      " · ",
      `Failures in a row: ${source.consecutive_failures}`,
    ]),
    errorLine,
    el("div", { class: "mt-2" }, [toggleBtn, runNowBtn, editBtn, toggleRuns]),
    runsSlot,
  ]);
}
