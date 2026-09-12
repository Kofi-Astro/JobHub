/**
 * Job detail page controller (job.html?id=…).
 *
 * Loads one job, renders it with a large, unmissable Apply action, records the
 * view (beacon), and — on Apply — records the click then sends the user to the
 * real application URL. The application path is always direct (brief).
 */
import { api, ApiError } from "../api/client.js";
import { el, mount, icons } from "../util/dom.js";
import { formatSalary, humanizeEnum, initials, timeAgo } from "../util/format.js";
import { isJobSaved, toggleSavedJob, recordRecentView } from "../store/state.js";
import { restoreSession, isLoggedIn, isJobSavedAccount, toggleSavedJobAccount } from "../auth.js";

function savedBackend() {
  return isLoggedIn()
    ? { check: isJobSavedAccount, toggle: toggleSavedJobAccount }
    : { check: isJobSaved, toggle: toggleSavedJob };
}

export async function initJobDetailPage() {
  const root = document.getElementById("job-root");
  const id = new URLSearchParams(location.search).get("id");
  if (!id) {
    mount(root, notFound());
    return;
  }

  await restoreSession(); // so the save button reflects account state, if any
  try {
    const job = await api.getJob(id);
    document.title = `${job.title} · ${job.company_name} — JobHub`;
    mount(root, render(job));
    recordRecentView(job);
    api.recordView(job.id); // fire-and-forget
  } catch (err) {
    mount(root, err instanceof ApiError && err.status === 404 ? notFound() : loadError());
  }
}

function render(job) {
  const logo = job.company_logo_url
    ? el("img", { src: job.company_logo_url, alt: "", class: "h-14 w-14 rounded-xl object-contain ring-1 ring-slate-200" })
    : el("div", { class: "grid h-14 w-14 place-items-center rounded-xl bg-slate-100 text-sm font-bold text-ink-500" }, initials(job.company_name));

  const applyButton = buildApplyControl(job);

  const badges = el("div", { class: "mt-3 flex flex-wrap gap-1.5" }, [
    job.is_remote && el("span", { class: "badge badge-remote" }, job.remote_scope ? `Remote · ${job.remote_scope}` : "Remote"),
    job.workplace_type === "hybrid" && el("span", { class: "badge badge-neutral" }, "Hybrid"),
    el("span", { class: "badge badge-neutral" }, humanizeEnum(job.job_type)),
    job.experience_level !== "unknown" && el("span", { class: "badge badge-neutral" }, humanizeEnum(job.experience_level)),
    job.is_direct_from_employer && el("span", { class: "badge badge-employer" }, "Direct from employer"),
    job.visa_sponsorship === true && el("span", { class: "badge badge-neutral" }, "Visa sponsorship"),
  ]);

  const facts = el("dl", { class: "grid grid-cols-2 gap-x-4 gap-y-3 text-sm sm:grid-cols-3" }, [
    fact("Location", job.location_label),
    fact("Salary", formatSalary(job.salary)),
    fact("Job type", humanizeEnum(job.job_type)),
    fact("Experience", job.experience_level === "unknown" ? "—" : humanizeEnum(job.experience_level)),
    fact("Source", job.source_label),
    fact("Posted", job.posted_at ? timeAgo(job.posted_at) : "—"),
  ]);

  const alsoOn =
    job.also_listed_on?.length > 0 &&
    el("div", { class: "mt-6 rounded-card border border-slate-200 bg-slate-50 p-4 text-sm" }, [
      el("p", { class: "font-medium text-ink-700" }, "Also listed on"),
      el(
        "ul",
        { class: "mt-1 space-y-1" },
        job.also_listed_on.map((s) =>
          el("li", {}, [
            s.source_url
              ? el("a", { href: s.source_url, target: "_blank", rel: "noopener", class: "text-brand-600 hover:underline" }, s.source_label)
              : s.source_label,
          ]),
        ),
      ),
    ]);

  const alreadySaved = savedBackend().check(job.id);
  const saveBtn = el(
    "button",
    {
      type: "button",
      class: "btn-ghost",
      onClick: async () => {
        saveBtn.disabled = true;
        try {
          const nowSaved = await savedBackend().toggle(job);
          saveBtn.innerHTML = "";
          saveBtn.append(
            spanIcon(nowSaved ? icons.bookmarkFilled : icons.bookmark),
            document.createTextNode(nowSaved ? "Saved" : "Save job"),
          );
        } finally {
          saveBtn.disabled = false;
        }
      },
    },
    [spanIcon(alreadySaved ? icons.bookmarkFilled : icons.bookmark), alreadySaved ? "Saved" : "Save job"],
  );

  return el("div", { class: "mx-auto max-w-3xl" }, [
    el("a", { href: "index.html", class: "inline-flex items-center gap-1 text-sm text-ink-500 hover:text-ink-800" }, "← Back to search"),

    el("div", { class: "mt-4 rounded-card border border-slate-200 bg-white p-5 shadow-card sm:p-6" }, [
      el("div", { class: "flex items-start gap-4" }, [
        logo,
        el("div", { class: "min-w-0 flex-1" }, [
          el("h1", { class: "text-xl font-bold text-ink-900 sm:text-2xl" }, job.title),
          el("p", { class: "mt-0.5 text-ink-700" }, [
            job.company_slug
              ? el("a", { href: `index.html?q=${encodeURIComponent(job.company_name)}`, class: "hover:underline" }, job.company_name)
              : job.company_name,
          ]),
          badges,
        ]),
      ]),

      el("div", { class: "mt-5 flex flex-wrap gap-2" }, [applyButton, saveBtn]),
      el("hr", { class: "my-5 border-slate-100" }),
      facts,
    ]),

    el("article", { class: "prose-job mt-6 rounded-card border border-slate-200 bg-white p-5 sm:p-6" }, [
      el("h2", { class: "!mt-0 text-lg font-bold text-ink-900" }, "About this role"),
      el("div", { html: job.description_html || "<p>No description provided.</p>" }),
    ]),

    alsoOn,

    // A second Apply button at the bottom so a long description doesn't hide it.
    el("div", { class: "mt-6 flex justify-center" }, [buildApplyControl(job, { big: true })]),
  ]);
}

/**
 * The Apply control. Records the click, then navigates to the real application
 * target. Handles url / email / instructions-only cases.
 */
function buildApplyControl(job, { big = false } = {}) {
  const cls = big ? "btn-primary px-8 py-3 text-base" : "btn-primary";

  if (job.apply_url) {
    return el(
      "a",
      {
        href: job.apply_url,
        target: "_blank",
        rel: "noopener",
        class: cls,
        onClick: () => api.applyClick(job.id).catch(() => {}),
      },
      ["Apply now", spanIcon(icons.external)],
    );
  }
  if (job.apply_email) {
    return el(
      "a",
      { href: `mailto:${job.apply_email}`, class: cls, onClick: () => api.applyClick(job.id).catch(() => {}) },
      `Apply by email`,
    );
  }
  return el(
    "div",
    { class: "rounded-lg border border-slate-300 bg-slate-50 p-3 text-sm text-ink-700" },
    job.apply_instructions || "See the description for how to apply.",
  );
}

function fact(label, value) {
  return el("div", {}, [
    el("dt", { class: "text-ink-400" }, label),
    el("dd", { class: "font-medium text-ink-900" }, value || "—"),
  ]);
}

function spanIcon(svg) {
  return el("span", { class: "inline-flex", html: svg });
}

function notFound() {
  return el("div", { class: "mx-auto max-w-md py-20 text-center" }, [
    el("p", { class: "text-lg font-semibold text-ink-800" }, "Job not found"),
    el("p", { class: "mt-1 text-sm text-ink-500" }, "It may have been filled or removed."),
    el("a", { href: "index.html", class: "btn-primary mt-4" }, "Browse jobs"),
  ]);
}

function loadError() {
  return el("div", { class: "mx-auto max-w-md py-20 text-center" }, [
    el("p", { class: "text-lg font-semibold text-ink-800" }, "Couldn't load this job"),
    el("button", { type: "button", class: "btn-ghost mt-4", onClick: () => location.reload() }, "Retry"),
  ]);
}
