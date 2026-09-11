/**
 * Job card — the single component used for every job in every listing context.
 *
 * IMPORTANT (brief): aggregated and employer jobs render identically. The only
 * difference is a small "Direct from employer" badge when
 * `job.is_direct_from_employer` is true. No layout, colour, or ordering bias.
 *
 * Shows: title, company (+ logo/initials), location, salary (or "Not
 * disclosed"), remote badge, posted date, source, and a save toggle.
 */
import { el, icons } from "../util/dom.js";
import { formatSalary, humanizeEnum, initials, timeAgo } from "../util/format.js";
import { isJobSaved, toggleSavedJob } from "../store/state.js";

/**
 * @param {object} job - a JobCard payload from the API
 * @param {{onSaveToggle?: Function}} [opts]
 * @returns {HTMLElement}
 */
export function jobCard(job, opts = {}) {
  const logo = job.company_logo_url
    ? el("img", {
        src: job.company_logo_url,
        alt: "",
        class: "h-10 w-10 rounded-lg object-contain bg-white ring-1 ring-slate-200",
        loading: "lazy",
      })
    : el(
        "div",
        {
          class:
            "grid h-10 w-10 place-items-center rounded-lg bg-slate-100 text-xs font-bold text-ink-500",
        },
        initials(job.company_name),
      );

  const meta = el("div", { class: "mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-ink-500" }, [
    metaItem(icons.pin, job.location_label),
    metaItem(icons.cash, formatSalary(job.salary)),
    metaItem(icons.clock, timeAgo(job.posted_at)),
  ]);

  const badges = el("div", { class: "mt-3 flex flex-wrap items-center gap-1.5" }, [
    job.is_remote && el("span", { class: "badge badge-remote" }, "Remote"),
    job.workplace_type === "hybrid" && el("span", { class: "badge badge-neutral" }, "Hybrid"),
    el("span", { class: "badge badge-neutral" }, humanizeEnum(job.job_type)),
    job.experience_level && job.experience_level !== "unknown"
      ? el("span", { class: "badge badge-neutral" }, humanizeEnum(job.experience_level))
      : null,
    job.is_direct_from_employer &&
      el("span", { class: "badge badge-employer", title: "Posted directly by the hiring company" }, "Direct from employer"),
  ]);

  const saveBtn = el("button", {
    type: "button",
    class:
      "shrink-0 rounded-lg p-2 text-ink-400 transition hover:bg-slate-100 hover:text-brand-500",
    "aria-label": isJobSaved(job.id) ? "Unsave job" : "Save job",
    "aria-pressed": String(isJobSaved(job.id)),
    onClick: (e) => {
      e.preventDefault();
      e.stopPropagation();
      const nowSaved = toggleSavedJob(job);
      saveBtn.innerHTML = nowSaved ? icons.bookmarkFilled : icons.bookmark;
      saveBtn.setAttribute("aria-pressed", String(nowSaved));
      saveBtn.classList.toggle("text-brand-500", nowSaved);
      opts.onSaveToggle?.(job, nowSaved);
    },
    html: isJobSaved(job.id) ? icons.bookmarkFilled : icons.bookmark,
  });
  if (isJobSaved(job.id)) saveBtn.classList.add("text-brand-500");

  return el("a", { href: `job.html?id=${job.id}`, class: "job-card group" }, [
    el("div", { class: "flex items-start gap-3" }, [
      logo,
      el("div", { class: "min-w-0 flex-1" }, [
        el(
          "h3",
          { class: "truncate text-[15px] font-semibold text-ink-900 group-hover:text-brand-600" },
          job.title,
        ),
        el("p", { class: "truncate text-sm text-ink-700" }, [
          job.company_name,
          el("span", { class: "text-ink-400" }, `  ·  ${job.source_label}`),
        ]),
        meta,
        badges,
      ]),
      saveBtn,
    ]),
  ]);
}

function metaItem(iconSvg, text) {
  if (!text) return null;
  return el("span", { class: "inline-flex items-center gap-1" }, [
    el("span", { class: "text-ink-400", html: iconSvg }),
    text,
  ]);
}
