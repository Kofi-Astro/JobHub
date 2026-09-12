/**
 * Session management for the frontend.
 *
 * The access token lives ONLY in memory (a module-level variable) — never in
 * localStorage — so it can't be lifted by an XSS payload reading storage. On
 * every page load we try a silent refresh against the httpOnly refresh-token
 * cookie (`POST /api/auth/refresh`); if that succeeds the visitor is signed in
 * again with no visible flicker. The refresh token itself is never touched by
 * this module — the browser sends the cookie automatically.
 *
 * On the FIRST successful sign-in this tab sees, anonymous localStorage saved
 * jobs are merged into the account once (`api.mergeAnon`) and then cleared, so
 * saved jobs stop double-tracking between localStorage and the account.
 */
import { api, setAccessToken } from "./api/client.js";
import { exportForMerge, clearSavedJobs } from "./store/state.js";

let currentUser = null;
let restorePromise = null; // memoized so concurrent callers share one refresh

// Job ids the logged-in seeker has saved, mirrored from the account API so
// job cards can render the bookmark as filled without a per-card fetch. Empty
// (and unused) whenever there is no logged-in seeker — jobCard.js falls back
// to the localStorage-backed `store/state.js` functions in that case.
let savedJobIds = new Set();

async function refreshSavedJobIds() {
  if (!currentUser || currentUser.role !== "seeker") {
    savedJobIds = new Set();
    return;
  }
  try {
    const rows = await api.savedJobs();
    savedJobIds = new Set(rows.map((r) => r.job.id));
  } catch {
    /* leave the previous cache in place rather than surprise-unsaving things */
  }
}

/** Account-backed equivalent of `store/state.js#isJobSaved`. */
export function isJobSavedAccount(jobId) {
  return savedJobIds.has(jobId);
}

/** Account-backed equivalent of `store/state.js#toggleSavedJob`. Returns the
 * new saved state (true = now saved), like its localStorage counterpart. */
export async function toggleSavedJobAccount(job) {
  if (savedJobIds.has(job.id)) {
    await api.unsaveJob(job.id);
    savedJobIds.delete(job.id);
    return false;
  }
  await api.saveJob(job.id);
  savedJobIds.add(job.id);
  return true;
}

/** Fire when sign-in state changes, so components can re-render (e.g. the
 * save button switching from localStorage to the account API). */
function notify() {
  window.dispatchEvent(new CustomEvent("authchange", { detail: currentUser }));
}

export function getUser() {
  return currentUser;
}

export function isLoggedIn() {
  return currentUser != null;
}

async function afterAuth(tokenResponse) {
  setAccessToken(tokenResponse.access_token);
  currentUser = tokenResponse.user;

  if (currentUser.role === "seeker") {
    const anon = exportForMerge();
    if (anon.saved_job_ids.length) {
      try {
        await api.mergeAnon(anon);
        clearSavedJobs(); // now tracked server-side; avoid double bookkeeping
      } catch {
        /* non-fatal — the user's local saves just stay local this session */
      }
    }
    await refreshSavedJobIds();
  }
  notify();
}

export async function registerSeeker({ email, password, fullName }) {
  const res = await api.registerSeeker({ email, password, full_name: fullName || undefined });
  await afterAuth(res);
  return res.user;
}

export async function login(email, password) {
  const res = await api.login({ email, password });
  await afterAuth(res);
  return res.user;
}

export async function logout() {
  try {
    await api.logout();
  } finally {
    setAccessToken(null);
    currentUser = null;
    savedJobIds = new Set();
    notify();
  }
}

/**
 * Attempt the silent refresh, once per page load. Safe to call from multiple
 * places (each page's own bootstrap AND shared components like `authNav`) —
 * every caller in the same tick awaits the SAME in-flight request rather than
 * racing each other or seeing a stale "not logged in" result.
 */
export function restoreSession() {
  if (!restorePromise) {
    restorePromise = (async () => {
      try {
        const res = await api.refresh();
        setAccessToken(res.access_token);
        currentUser = res.user;
        await refreshSavedJobIds();
        notify();
      } catch {
        currentUser = null; // no valid session cookie — a normal, common case
      }
      return currentUser;
    })();
  }
  return restorePromise;
}
