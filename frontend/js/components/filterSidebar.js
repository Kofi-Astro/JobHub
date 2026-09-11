/**
 * The persistent, collapsible filter sidebar with live result counts (brief).
 *
 * Stateless render: given the current `filters` (from the URL), the `facets`
 * (counts from the API), and the reference data (`taxonomy`, `countries`,
 * `sources`), it builds the panel. Every control, on change, produces a NEW
 * filter object and calls `onChange(next)` — the page then writes it to the URL,
 * which triggers a re-fetch and a re-render. One-way data flow, no local state
 * except which sections are collapsed.
 *
 * Layout: a normal column on `lg+`; a slide-up bottom sheet under `lg` (toggled
 * by the "Filters" button in the results header).
 */
import { el, icons } from "../util/dom.js";
import { humanizeEnum } from "../util/format.js";
import { toggleMulti } from "../util/url.js";

const collapsed = new Set(); // section keys the user has folded (session-only)

const WORKPLACE = ["remote", "hybrid", "onsite"];
const JOB_TYPES = ["full_time", "part_time", "contract", "internship"];
const EXPERIENCE = ["entry", "mid", "senior", "lead"];
const DATE_OPTIONS = [
  ["Any time", undefined],
  ["Past 24 hours", 1],
  ["Past week", 7],
  ["Past month", 30],
];

export function filterSidebar({ filters, facets, taxonomy, countries, sources, onChange }) {
  const f = filters;
  const countFor = (list, value) =>
    (list || []).find((x) => x.value === value || x.value === String(value))?.count ?? 0;

  // Emit a new filter object with `patch` applied and page reset to 1.
  const emit = (patch) => onChange({ ...f, ...patch, page: 1 });

  const panel = el("div", { class: "space-y-1" }, [
    activeCount(f) > 0 &&
      el(
        "button",
        {
          type: "button",
          class: "mb-1 text-sm font-medium text-brand-600 hover:underline",
          onClick: () => onChange({ q: f.q, page: 1 }),
        },
        `Clear all filters (${activeCount(f)})`,
      ),

    // --- Field / sub-field ---
    section("category", "Category", [
      ...(taxonomy?.fields || []).map((field) =>
        taxonomyField(field, f, facets, emit, countFor),
      ),
    ]),

    // --- Workplace ---
    section("workplace", "Workplace", [
      row("checkbox-group", null, [
        ...WORKPLACE.map((w) =>
          checkRow({
            label: humanizeEnum(w),
            checked: (f.workplace || []).includes(w),
            count: countFor(facets?.workplace_types, w),
            onToggle: () => emit({ workplace: toggleMulti(f.workplace, w) }),
          }),
        ),
      ]),
    ]),

    // --- Job type ---
    section("job_type", "Job type", [
      ...JOB_TYPES.map((t) =>
        checkRow({
          label: humanizeEnum(t),
          checked: (f.job_type || []).includes(t),
          count: countFor(facets?.job_types, t),
          onToggle: () => emit({ job_type: toggleMulti(f.job_type, t) }),
        }),
      ),
    ]),

    // --- Experience ---
    section("experience", "Experience level", [
      ...EXPERIENCE.map((x) =>
        checkRow({
          label: humanizeEnum(x),
          checked: (f.experience || []).includes(x),
          count: countFor(facets?.experience_levels, x),
          onToggle: () => emit({ experience: toggleMulti(f.experience, x) }),
        }),
      ),
    ]),

    // --- Salary ---
    section("salary", "Salary (annualised)", [salaryControls(f, emit)]),

    // --- Date posted ---
    section("date", "Date posted", [
      ...DATE_OPTIONS.map(([label, days]) =>
        radioRow({
          name: "posted_within_days",
          label,
          checked: (f.posted_within_days || undefined) === days,
          onSelect: () => emit({ posted_within_days: days }),
        }),
      ),
    ]),

    // --- Country ---
    (countries?.length || 0) > 0 &&
      section("country", "Country / region", [
        ...countries.map((c) =>
          checkRow({
            label: `${c.name}`,
            checked: (f.country || []).includes(c.code),
            count: c.job_count,
            onToggle: () => emit({ country: toggleMulti(f.country, c.code) }),
          }),
        ),
      ]),

    // --- Source ---
    (sources?.length || 0) > 0 &&
      section("source", "Source", [
        ...sources.map((s) =>
          s.key === "employer"
            ? checkRow({
                label: "Direct from employer",
                checked: !!f.employer_only,
                count: s.job_count,
                onToggle: () => emit({ employer_only: !f.employer_only }),
              })
            : checkRow({
                label: s.name,
                checked: (f.source || []).includes(s.key),
                count: s.job_count,
                onToggle: () => emit({ source: toggleMulti(f.source, s.key) }),
              }),
        ),
      ]),

    // --- Visa (only if the data supports it) ---
    (facets?.total != null && hasVisaData(facets)) &&
      section("visa", "Visa", [
        checkRow({
          label: "Offers visa sponsorship",
          checked: f.visa_sponsorship === true,
          onToggle: () =>
            emit({ visa_sponsorship: f.visa_sponsorship === true ? undefined : true }),
        }),
      ]),
  ]);

  return panel;
}

// --- section / row primitives -----------------------------------------

function section(key, title, children) {
  const isCollapsed = collapsed.has(key);
  const body = el("div", { class: isCollapsed ? "hidden" : "mt-1 space-y-0.5" }, children);
  const chevron = el("span", {
    class: `text-ink-400 transition-transform ${isCollapsed ? "-rotate-90" : ""}`,
    html: icons.chevron,
  });
  const header = el(
    "button",
    {
      type: "button",
      class:
        "flex w-full items-center justify-between py-2 text-sm font-semibold text-ink-800",
      onClick: () => {
        collapsed.has(key) ? collapsed.delete(key) : collapsed.add(key);
        body.classList.toggle("hidden");
        chevron.classList.toggle("-rotate-90");
      },
    },
    [title, chevron],
  );
  return el("div", { class: "border-b border-slate-100 pb-2" }, [header, body]);
}

function row(_type, _label, children) {
  return el("div", { class: "space-y-0.5" }, children);
}

function checkRow({ label, checked, count, onToggle }) {
  return el("label", { class: "filter-row" }, [
    el("span", { class: "flex items-center gap-2" }, [
      el("input", {
        type: "checkbox",
        checked: checked || null,
        class: "h-4 w-4 rounded border-slate-300 text-brand-500 focus:ring-brand-500",
        onChange: onToggle,
      }),
      el("span", { class: checked ? "font-medium text-ink-900" : "text-ink-700" }, label),
    ]),
    count != null && el("span", { class: "filter-count" }, count.toLocaleString()),
  ]);
}

function radioRow({ name, label, checked, onSelect }) {
  return el("label", { class: "filter-row" }, [
    el("span", { class: "flex items-center gap-2" }, [
      el("input", {
        type: "radio",
        name,
        checked: checked || null,
        class: "h-4 w-4 border-slate-300 text-brand-500 focus:ring-brand-500",
        onChange: onSelect,
      }),
      el("span", { class: checked ? "font-medium text-ink-900" : "text-ink-700" }, label),
    ]),
  ]);
}

// --- taxonomy (field with nested sub-fields) ------------------------

function taxonomyField(field, f, facets, emit, countFor) {
  const fieldChecked = (f.field || []).includes(field.slug);
  const subRows = field.subfields.map((sf) =>
    checkRow({
      label: sf.name,
      checked: (f.subfield || []).includes(sf.slug),
      count: countFor(facets?.subfields, sf.slug),
      onToggle: () => emit({ subfield: toggleMulti(f.subfield, sf.slug) }),
    }),
  );
  const kids = el("div", { class: "ml-5 border-l border-slate-100 pl-2" }, subRows);
  const open = fieldChecked || (f.subfield || []).some((s) => field.subfields.some((sf) => sf.slug === s));
  if (!open) kids.classList.add("hidden");

  const toggleKids = el("button", {
    type: "button",
    class: `text-ink-400 ${open ? "" : "-rotate-90"} transition-transform`,
    html: icons.chevron,
    onClick: () => kids.classList.toggle("hidden"),
  });

  return el("div", {}, [
    el("div", { class: "filter-row" }, [
      el("label", { class: "flex flex-1 items-center gap-2" }, [
        el("input", {
          type: "checkbox",
          checked: fieldChecked || null,
          class: "h-4 w-4 rounded border-slate-300 text-brand-500 focus:ring-brand-500",
          onChange: () => emit({ field: toggleMulti(f.field, field.slug) }),
        }),
        el("span", { class: fieldChecked ? "font-medium text-ink-900" : "text-ink-800" }, field.name),
      ]),
      el("span", { class: "flex items-center gap-1.5" }, [
        el("span", { class: "filter-count" }, countFor(facets?.fields, field.slug).toLocaleString()),
        toggleKids,
      ]),
    ]),
    kids,
  ]);
}

// --- salary controls -------------------------------------------------

function salaryControls(f, emit) {
  const input = (name, placeholder) =>
    el("input", {
      type: "number",
      min: "0",
      step: "1000",
      inputmode: "numeric",
      placeholder,
      value: f[name] ?? "",
      class:
        "w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm focus:border-brand-400",
      onChange: (e) => {
        const v = e.target.value ? Number(e.target.value) : undefined;
        emit({ [name]: v });
      },
    });

  return el("div", { class: "space-y-2 px-2 pt-1" }, [
    el("div", { class: "flex items-center gap-2" }, [
      input("salary_min", "Min"),
      el("span", { class: "text-ink-400" }, "–"),
      input("salary_max", "Max"),
    ]),
    el("label", { class: "flex items-center gap-2 text-sm text-ink-700" }, [
      el("input", {
        type: "checkbox",
        // default is "included"; unchecked means the user opted out
        checked: f.include_undisclosed_salary !== false ? "" : null,
        class: "h-4 w-4 rounded border-slate-300 text-brand-500",
        onChange: (e) =>
          emit({ include_undisclosed_salary: e.target.checked ? undefined : false }),
      }),
      'Include "not disclosed"',
    ]),
  ]);
}

// --- helpers --------------------------------------------------------

function activeCount(f) {
  let n = 0;
  for (const k of ["field", "subfield", "country", "workplace", "job_type", "experience", "source"]) {
    n += (f[k] || []).length;
  }
  for (const k of ["salary_min", "salary_max", "posted_within_days", "remote", "employer_only", "visa_sponsorship"]) {
    if (f[k]) n += 1;
  }
  return n;
}

function hasVisaData(_facets) {
  // The backend only sets `visa_sponsorship` from the employer checkbox; until
  // employer posting ships (M10) there is never any data, so hide the filter.
  return false;
}
