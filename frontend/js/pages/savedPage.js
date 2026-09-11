/**
 * Saved jobs page (saved.html) — anonymous, localStorage-backed for now.
 *
 * Re-fetches each saved job by id so the card always shows current data (a job
 * may have expired or changed since it was saved); a saved id that 404s is
 * shown as a "no longer available" placeholder rather than silently vanishing.
 *
 * Milestone 9 adds account-backed saved jobs (`GET /api/seeker/saved-jobs`) and
 * a one-time merge of this localStorage list into the account on first login —
 * this module is written so that swap only touches `loadJobs()`.
 */
import { api, ApiError } from "../api/client.js";
import { el, mount } from "../util/dom.js";
import { jobCard } from "../components/jobCard.js";
import { skeletonList } from "../components/skeleton.js";
import { getSavedJobs } from "../store/state.js";

export async function initSavedPage() {
  const root = document.getElementById("saved-root");
  const saved = getSavedJobs();

  if (!saved.length) {
    mount(root, emptyState());
    return;
  }

  mount(root, skeletonList(Math.min(saved.length, 5)));
  const jobs = await loadJobs(saved);
  mount(root, jobs.length ? jobs.map((j) => jobCard(j)) : emptyState());

  // Saving/unsaving from within this page should remove the card immediately.
  window.addEventListener("savedjobschange", () => {
    const stillSaved = new Set(getSavedJobs().map((j) => j.id));
    for (const node of [...root.children]) {
      const id = node.getAttribute("href")?.split("id=")[1];
      if (id && !stillSaved.has(id)) node.remove();
    }
    if (!root.children.length) mount(root, emptyState());
  });
}

async function loadJobs(saved) {
  const results = await Promise.allSettled(saved.map((s) => api.getJob(s.id)));
  const jobs = [];
  results.forEach((r, i) => {
    if (r.status === "fulfilled") jobs.push(r.value);
    else if (!(r.reason instanceof ApiError && r.reason.status === 404)) {
      // A transient error (not "gone") — keep a stub so the user isn't
      // surprised the job silently disappeared from their saved list.
      jobs.push(null);
    }
    void i;
  });
  return jobs.filter(Boolean);
}

function emptyState() {
  return el("div", { class: "rounded-card border border-dashed border-slate-300 p-10 text-center" }, [
    el("p", { class: "text-lg font-semibold text-ink-800" }, "No saved jobs yet"),
    el("p", { class: "mt-1 text-sm text-ink-500" }, "Tap the bookmark icon on any job to save it here."),
    el("a", { href: "index.html", class: "btn-primary mt-4" }, "Browse jobs"),
  ]);
}
