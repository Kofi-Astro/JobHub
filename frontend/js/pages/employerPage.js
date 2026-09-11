/**
 * Employer portal page controller (employer.html).
 *
 * Two states, switched purely on auth:
 *   - logged out (or logged in as a seeker) → register/sign-in forms
 *   - logged in as an employer               → dashboard: post a job, list of
 *     "my jobs" with status + view/apply-click counts, edit/close/republish.
 *
 * Employers get their OWN registration here (brief: a clearly separate,
 * signposted entry point from the job-seeker experience) — this never reuses
 * account.html's seeker forms.
 */
import { el, mount } from "../util/dom.js";
import { humanizeEnum } from "../util/format.js";
import { api, ApiError } from "../api/client.js";
import { restoreSession, getUser, isLoggedIn, login, logout } from "../auth.js";

let taxonomy = null;

export async function initEmployerPage() {
  const root = document.getElementById("employer-root");
  await restoreSession();
  await render(root);
  window.addEventListener("authchange", () => render(root));
}

async function render(root) {
  const user = getUser();
  if (isLoggedIn() && user.role === "employer") {
    mount(root, await dashboardView(user));
  } else if (isLoggedIn()) {
    // Signed in, but as a seeker/admin — this portal is employer-only.
    mount(
      root,
      el("div", { class: "mx-auto max-w-md rounded-card border border-amber-200 bg-amber-50 p-6 text-center" }, [
        el("p", { class: "font-medium text-amber-800" }, "You're signed in with a job-seeker account."),
        el("p", { class: "mt-1 text-sm text-amber-700" }, "Sign out to register or sign in as an employer."),
        el("button", { type: "button", class: "btn-ghost mt-4", onClick: async () => { await logout(); render(root); } }, "Sign out"),
      ]),
    );
  } else {
    mount(root, authView(root));
  }
}

// ---------------------------------------------------------------------------
// Auth (register / sign in)
// ---------------------------------------------------------------------------

function authView(root) {
  let mode = "register";
  const wrap = el("div", {});
  const draw = () => mount(wrap, mode === "register" ? registerForm() : signInForm());
  function registerForm() {
    return formCard(
      "Post jobs directly on JobHub",
      "Create a free employer account. New accounts are reviewed before your first posting goes live.",
      employerRegisterForm(root),
      ["Already have an employer account? ", linkBtn("Sign in", () => { mode = "signin"; draw(); })],
    );
  }
  function signInForm() {
    return formCard(
      "Employer sign in",
      "",
      employerSignInForm(root),
      ["New here? ", linkBtn("Create an employer account", () => { mode = "register"; draw(); })],
    );
  }
  draw();
  return wrap;
}

function formCard(title, subtitle, form, footerParts) {
  return el("div", { class: "mx-auto max-w-lg rounded-card border border-slate-200 bg-white p-6 shadow-card" }, [
    el("h1", { class: "text-xl font-bold text-ink-900" }, title),
    subtitle && el("p", { class: "mt-1 text-sm text-ink-500" }, subtitle),
    el("div", { class: "mt-5" }, form),
    el("p", { class: "mt-5 text-center text-sm text-ink-500" }, footerParts),
  ]);
}

function linkBtn(label, onClick) {
  return el("button", { type: "button", class: "font-medium text-brand-600 hover:underline", onClick }, label);
}

function labeled(label, input) {
  return el("label", { class: "block text-sm" }, [
    el("span", { class: "mb-1 block font-medium text-ink-700" }, label),
    input,
  ]);
}

function inputEl(attrs) {
  return el("input", { class: "w-full rounded-lg border border-slate-300 px-3 py-2", ...attrs });
}

function employerRegisterForm(root) {
  const name = inputEl({ type: "text", autocomplete: "name" });
  const jobTitle = inputEl({ type: "text" });
  const company = inputEl({ type: "text", required: true });
  const website = inputEl({ type: "url", placeholder: "https://" });
  const email = inputEl({ type: "email", required: true, autocomplete: "email" });
  const password = inputEl({ type: "password", required: true, minlength: "8", autocomplete: "new-password" });
  const errorSlot = el("div", {});
  const submitBtn = el("button", { type: "submit", class: "btn-primary w-full" }, "Create employer account");

  return el(
    "form",
    {
      class: "space-y-4",
      onSubmit: async (e) => {
        e.preventDefault();
        submitBtn.disabled = true;
        try {
          await api.registerEmployer({
            email: email.value.trim(),
            password: password.value,
            full_name: name.value.trim() || undefined,
            job_title: jobTitle.value.trim() || undefined,
            company_name: company.value.trim(),
            company_website: website.value.trim() || undefined,
          });
          await login(email.value.trim(), password.value);
          await render(root);
        } catch (err) {
          mount(errorSlot, errorBox(err));
        } finally {
          submitBtn.disabled = false;
        }
      },
    },
    [
      labeled("Company name", company),
      labeled("Company website (optional)", website),
      labeled("Your name", name),
      labeled("Your job title (optional)", jobTitle),
      labeled("Work email", email),
      labeled("Password", password),
      errorSlot,
      submitBtn,
    ],
  );
}

function employerSignInForm(root) {
  const email = inputEl({ type: "email", required: true, autocomplete: "email" });
  const password = inputEl({ type: "password", required: true, autocomplete: "current-password" });
  const errorSlot = el("div", {});
  const submitBtn = el("button", { type: "submit", class: "btn-primary w-full" }, "Sign in");

  return el(
    "form",
    {
      class: "space-y-4",
      onSubmit: async (e) => {
        e.preventDefault();
        submitBtn.disabled = true;
        try {
          const user = await login(email.value.trim(), password.value);
          if (user.role !== "employer") {
            mount(errorSlot, errorBox(new Error("This is not an employer account.")));
            await logout();
            return;
          }
          await render(root);
        } catch (err) {
          mount(errorSlot, errorBox(err));
        } finally {
          submitBtn.disabled = false;
        }
      },
    },
    [labeled("Work email", email), labeled("Password", password), errorSlot, submitBtn],
  );
}

function errorBox(err) {
  const msg = err instanceof ApiError ? err.message : "Something went wrong. Try again.";
  return el("p", { class: "rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700" }, msg);
}

// ---------------------------------------------------------------------------
// Dashboard
// ---------------------------------------------------------------------------

async function dashboardView(user) {
  const [me, jobs, stats] = await Promise.all([api.me(), api.employerJobs(), api.employerStats()]);
  taxonomy ??= await api.taxonomy();

  const container = el("div", { class: "mx-auto max-w-4xl space-y-6" });
  const jobsSlot = el("div", { class: "space-y-3" });
  const formSlot = el("div", {});

  const refreshJobs = async () => {
    const rows = await api.employerJobs();
    mount(jobsSlot, rows.length ? rows.map((j) => jobRow(j, refreshJobs, formSlot)) : emptyJobs());
  };

  mount(jobsSlot, jobs.length ? jobs.map((j) => jobRow(j, refreshJobs, formSlot)) : emptyJobs());

  mount(container, [
    header(user, me),
    me.employer?.account_status !== "approved" && accountStatusBanner(me.employer.account_status),
    statsBar(stats),
    el("div", { class: "flex items-center justify-between" }, [
      el("h2", { class: "text-lg font-bold text-ink-900" }, "My job postings"),
      el(
        "button",
        {
          type: "button",
          class: "btn-primary",
          onClick: () => mount(formSlot, postForm(null, () => { mount(formSlot, ""); refreshJobs(); })),
        },
        "+ Post a job",
      ),
    ]),
    formSlot,
    jobsSlot,
  ]);
  return container;
}

function header(user, me) {
  return el("div", { class: "flex items-center justify-between" }, [
    el("div", {}, [
      el("h1", { class: "text-xl font-bold text-ink-900" }, me.employer?.company_name || "Your company"),
      el("p", { class: "text-sm text-ink-500" }, user.email),
    ]),
    el("button", { type: "button", class: "btn-ghost", onClick: () => logout().then(() => location.reload()) }, "Sign out"),
  ]);
}

function accountStatusBanner(status) {
  const copy = {
    pending: ["Your employer account is awaiting approval.", "You can prepare postings now — they'll go live once your account and first posting are reviewed."],
    rejected: ["Your employer account was not approved.", "Contact support if you think this is a mistake."],
    suspended: ["Your employer account has been suspended.", "Contact support for details."],
  }[status] || [humanizeEnum(status), ""];
  return el("div", { class: "rounded-card border border-amber-200 bg-amber-50 p-4" }, [
    el("p", { class: "font-medium text-amber-800" }, copy[0]),
    el("p", { class: "text-sm text-amber-700" }, copy[1]),
  ]);
}

function statsBar(stats) {
  const tile = (label, value) =>
    el("div", { class: "rounded-card border border-slate-200 bg-white p-4 text-center" }, [
      el("div", { class: "text-2xl font-bold text-ink-900" }, String(value)),
      el("div", { class: "text-xs text-ink-500" }, label),
    ]);
  return el("div", { class: "grid grid-cols-2 gap-3 sm:grid-cols-4" }, [
    tile("Active", stats.active_jobs),
    tile("Pending review", stats.pending_jobs),
    tile("Total views", stats.total_views),
    tile("Apply clicks", stats.total_apply_clicks),
  ]);
}

function emptyJobs() {
  return el("p", { class: "rounded-card border border-dashed border-slate-300 p-8 text-center text-sm text-ink-500" }, "No postings yet.");
}

const STATUS_BADGE = {
  active: "badge-remote",
  pending: "badge-neutral",
  rejected: "badge-neutral",
  closed: "badge-neutral",
  expired: "badge-neutral",
};

function jobRow(job, refresh, formSlot) {
  const actions = [];
  if (job.status === "closed") {
    actions.push(actionBtn("Republish", async () => { await api.republishJob(job.id); refresh(); }));
  } else {
    actions.push(actionBtn("Edit", () => mount(formSlot, postForm(job, () => { mount(formSlot, ""); refresh(); }))));
    if (job.status === "active" || job.status === "pending") {
      actions.push(actionBtn("Close", async () => { await api.closeJob(job.id); refresh(); }));
    }
  }

  return el("div", { class: "job-card flex items-center justify-between gap-3" }, [
    el("div", { class: "min-w-0" }, [
      el("p", { class: "truncate font-semibold text-ink-900" }, job.title),
      el("p", { class: "text-sm text-ink-500" }, job.location_label),
      el("div", { class: "mt-1 flex items-center gap-2 text-xs text-ink-400" }, [
        el("span", { class: `badge ${STATUS_BADGE[job.status] || "badge-neutral"}` }, humanizeEnum(job.status)),
        job.moderation_status === "pending" && el("span", { class: "badge badge-neutral" }, "Awaiting review"),
        `${job.view_count} views`,
        `${job.apply_click_count} clicks`,
      ]),
    ]),
    el("div", { class: "flex shrink-0 gap-2" }, actions),
  ]);
}

function actionBtn(label, onClick) {
  return el("button", { type: "button", class: "btn-ghost px-3 py-1.5 text-sm", onClick }, label);
}

// ---------------------------------------------------------------------------
// Posting form (create or edit)
// ---------------------------------------------------------------------------

function postForm(existing, onDone) {
  const isEdit = !!existing;
  const title = inputEl({ type: "text", required: true, value: existing?.title || "" });
  const description = el("textarea", {
    rows: "6",
    required: true,
    class: "w-full rounded-lg border border-slate-300 px-3 py-2",
  }, existing ? "" : "");

  const fieldSelect = selectEl(
    taxonomy.fields.map((f) => [f.slug, f.name]),
    existing?.field_slug,
  );
  const subfieldSelect = selectEl([], existing?.subfield_slug);
  const populateSubfields = () => {
    const f = taxonomy.fields.find((x) => x.slug === fieldSelect.value);
    mount(subfieldSelect, (f?.subfields || []).map((s) => optionEl(s.slug, s.name)));
  };
  fieldSelect.addEventListener("change", populateSubfields);
  populateSubfields();
  if (existing?.subfield_slug) subfieldSelect.value = existing.subfield_slug;

  const workplace = selectEl(
    [["remote", "Remote"], ["hybrid", "Hybrid"], ["onsite", "On-site"]],
    existing?.workplace_type,
  );
  const city = inputEl({ type: "text", placeholder: "City" });
  const country = inputEl({ type: "text", placeholder: "Country code, e.g. US", maxlength: "2" });
  const remoteScope = inputEl({ type: "text", placeholder: 'e.g. "Worldwide", "US only"' });
  const locationRow = el("div", { class: "grid grid-cols-2 gap-3" }, [city, country]);
  const toggleLocationFields = () => {
    const remote = workplace.value === "remote";
    locationRow.classList.toggle("hidden", remote);
    remoteScope.parentElement?.classList.toggle("hidden", !remote);
  };
  workplace.addEventListener("change", toggleLocationFields);

  const jobType = selectEl(
    [["full_time", "Full-time"], ["part_time", "Part-time"], ["contract", "Contract"], ["internship", "Internship"], ["temporary", "Temporary"]],
    existing?.job_type,
  );
  const experience = selectEl(
    [["unknown", "Not specified"], ["entry", "Entry"], ["mid", "Mid"], ["senior", "Senior"], ["lead", "Lead"]],
    existing?.experience_level,
  );

  const salaryDisclosed = el("input", { type: "checkbox", class: "h-4 w-4 rounded border-slate-300 text-brand-500" });
  const salaryMin = inputEl({ type: "number", min: "0", placeholder: "Min" });
  const salaryMax = inputEl({ type: "number", min: "0", placeholder: "Max" });
  const salaryCurrency = inputEl({ type: "text", placeholder: "USD", maxlength: "3", value: "USD" });
  const salaryPeriod = selectEl([["year", "/year"], ["month", "/month"], ["week", "/week"], ["day", "/day"], ["hour", "/hour"]], "year");
  const salaryFields = el("div", { class: "mt-2 hidden grid-cols-4 gap-2" }, [salaryMin, salaryMax, salaryCurrency, salaryPeriod]);
  salaryDisclosed.addEventListener("change", () => {
    salaryFields.classList.toggle("hidden", !salaryDisclosed.checked);
    salaryFields.classList.toggle("grid", salaryDisclosed.checked);
  });

  const applyUrl = inputEl({ type: "url", placeholder: "https://yourcompany.com/careers/role" });
  const applyEmail = inputEl({ type: "email", placeholder: "jobs@yourcompany.com" });
  const visaSponsorship = el("input", { type: "checkbox", class: "h-4 w-4 rounded border-slate-300 text-brand-500", checked: existing?.visa_sponsorship || null });

  const errorSlot = el("div", {});
  const submitBtn = el("button", { type: "submit", class: "btn-primary" }, isEdit ? "Save changes" : "Submit for review");

  toggleLocationFields();

  return el(
    "form",
    {
      class: "job-card space-y-4",
      onSubmit: async (e) => {
        e.preventDefault();
        submitBtn.disabled = true;
        const payload = {
          title: title.value.trim(),
          description_html: `<p>${description.value.trim().replace(/\n\n+/g, "</p><p>").replace(/\n/g, "<br>")}</p>`,
          field_slug: fieldSelect.value,
          subfield_slug: subfieldSelect.value,
          workplace_type: workplace.value,
          city: workplace.value === "remote" ? null : city.value.trim() || null,
          country_code: workplace.value === "remote" ? null : country.value.trim().toUpperCase() || null,
          remote_scope: workplace.value === "remote" ? remoteScope.value.trim() || null : null,
          job_type: jobType.value,
          experience_level: experience.value,
          salary_is_disclosed: salaryDisclosed.checked,
          salary_min: salaryDisclosed.checked && salaryMin.value ? Number(salaryMin.value) : null,
          salary_max: salaryDisclosed.checked && salaryMax.value ? Number(salaryMax.value) : null,
          salary_currency: salaryDisclosed.checked ? salaryCurrency.value.trim().toUpperCase() || null : null,
          salary_period: salaryDisclosed.checked ? salaryPeriod.value : null,
          apply_url: applyUrl.value.trim() || null,
          apply_email: applyEmail.value.trim() || null,
          visa_sponsorship: visaSponsorship.checked,
        };
        try {
          if (isEdit) await api.updateEmployerJob(existing.id, payload);
          else await api.postJob(payload);
          onDone();
        } catch (err) {
          mount(errorSlot, errorBox(err));
        } finally {
          submitBtn.disabled = false;
        }
      },
    },
    [
      el("h3", { class: "text-lg font-bold text-ink-900" }, isEdit ? "Edit posting" : "New job posting"),
      labeled("Job title", title),
      labeled("Description", description),
      el("div", { class: "grid grid-cols-2 gap-3" }, [labeled("Field", fieldSelect), labeled("Sub-field", subfieldSelect)]),
      labeled("Workplace", workplace),
      locationRow,
      labeled("Remote scope (optional)", remoteScope),
      el("div", { class: "grid grid-cols-2 gap-3" }, [labeled("Job type", jobType), labeled("Experience level", experience)]),
      el("label", { class: "flex items-center gap-2 text-sm" }, [salaryDisclosed, "Disclose salary"]),
      salaryFields,
      el("div", { class: "grid grid-cols-2 gap-3" }, [
        labeled("Application URL", applyUrl),
        labeled("...or application email", applyEmail),
      ]),
      el("label", { class: "flex items-center gap-2 text-sm" }, [visaSponsorship, "This role offers visa sponsorship"]),
      errorSlot,
      el("div", { class: "flex gap-2" }, [submitBtn, el("button", { type: "button", class: "btn-ghost", onClick: onDone }, "Cancel")]),
    ],
  );
}

function selectEl(options, selected) {
  const sel = el("select", { class: "w-full rounded-lg border border-slate-300 bg-white px-3 py-2" },
    options.map(([value, label]) => optionEl(value, label)));
  if (selected) sel.value = selected;
  return sel;
}

function optionEl(value, label) {
  return el("option", { value }, label);
}
