/**
 * Saved jobs page (saved.html).
 *
 * Logged-in seekers: `GET /api/seeker/saved-jobs` already embeds each job, one
 * round trip. Anonymous visitors: the ids live in localStorage, so each job is
 * re-fetched individually — that also means the card always reflects current
 * data (a job may have expired since it was saved), and a ref that now 404s is
 * dropped rather than shown as a broken card.
 */
import { api, ApiError } from "../api/client.js";
import { el, mount } from "../util/dom.js";
import { jobCard } from "../components/jobCard.js";
import { skeletonList } from "../components/skeleton.js";
import { getSavedJobs } from "../store/state.js";
import { restoreSession, isLoggedIn } from "../auth.js";

export async function initSavedPage() {
  const root = document.getElementById("saved-root");
  await restoreSession();

  if (isLoggedIn()) {
    mount(root, skeletonList(4));
    const rows = await api.savedJobs();
    mount(root, rows.length ? rows.map((r) => jobCard(r.job)) : emptyState());
    return;
  }

  const saved = getSavedJobs();
  if (!saved.length) {
    mount(root, emptyState());
    return;
  }

  mount(root, skeletonList(Math.min(saved.length, 5)));
  const jobs = await loadAnonJobs(saved);
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

async function loadAnonJobs(saved) {
  const results = await Promise.allSettled(saved.map((s) => api.getJob(s.id)));
  const jobs = [];
  for (const r of results) {
    if (r.status === "fulfilled") jobs.push(r.value);
    else if (!(r.reason instanceof ApiError && r.reason.status === 404)) {
      // A transient error (not "gone") — surface nothing rather than guess;
      // the job simply won't appear this load.
      continue;
    }
  }
  return jobs;
}

function emptyState() {
  return el("div", { class: "rounded-card border border-dashed border-slate-300 p-10 text-center" }, [
    el("p", { class: "text-lg font-semibold text-ink-800" }, "No saved jobs yet"),
    el("p", { class: "mt-1 text-sm text-ink-500" }, "Tap the bookmark icon on any job to save it here."),
    el("a", { href: "index.html", class: "btn-primary mt-4" }, "Browse jobs"),
  ]);
}
