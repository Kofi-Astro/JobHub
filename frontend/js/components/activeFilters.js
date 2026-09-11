/**
 * The row of removable "chips" above the results showing every active filter,
 * so the user always sees what is narrowing their results and can undo any one
 * of them in a click.
 */
import { el } from "../util/dom.js";
import { humanizeEnum } from "../util/format.js";

/**
 * @param {object} filters
 * @param {{taxonomy?:object, countries?:Array, sources?:Array}} refs
 * @param {(next:object)=>void} onChange
 */
export function activeFilters(filters, refs, onChange) {
  const chips = [];
  const f = filters;

  const remove = (patch) => onChange({ ...f, ...patch, page: 1 });
  const dropFrom = (key, value) =>
    remove({ [key]: (f[key] || []).filter((v) => v !== value) });

  const fieldName = (slug) =>
    refs.taxonomy?.fields.find((x) => x.slug === slug)?.name || slug;
  const subfieldName = (slug) => {
    for (const fl of refs.taxonomy?.fields || []) {
      const s = fl.subfields.find((x) => x.slug === slug);
      if (s) return s.name;
    }
    return slug;
  };
  const countryName = (code) =>
    refs.countries?.find((c) => c.code === code)?.name || code;
  const sourceName = (key) => refs.sources?.find((s) => s.key === key)?.name || key;

  for (const slug of f.field || []) chips.push(chip(fieldName(slug), () => dropFrom("field", slug)));
  for (const slug of f.subfield || []) chips.push(chip(subfieldName(slug), () => dropFrom("subfield", slug)));
  for (const w of f.workplace || []) chips.push(chip(humanizeEnum(w), () => dropFrom("workplace", w)));
  for (const t of f.job_type || []) chips.push(chip(humanizeEnum(t), () => dropFrom("job_type", t)));
  for (const x of f.experience || []) chips.push(chip(humanizeEnum(x), () => dropFrom("experience", x)));
  for (const c of f.country || []) chips.push(chip(countryName(c), () => dropFrom("country", c)));
  for (const s of f.source || []) chips.push(chip(sourceName(s), () => dropFrom("source", s)));
  if (f.employer_only) chips.push(chip("Direct from employer", () => remove({ employer_only: undefined })));
  if (f.remote) chips.push(chip("Remote", () => remove({ remote: undefined })));
  if (f.salary_min) chips.push(chip(`≥ ${Number(f.salary_min).toLocaleString()}`, () => remove({ salary_min: undefined })));
  if (f.salary_max) chips.push(chip(`≤ ${Number(f.salary_max).toLocaleString()}`, () => remove({ salary_max: undefined })));
  if (f.posted_within_days)
    chips.push(chip(`Past ${f.posted_within_days}d`, () => remove({ posted_within_days: undefined })));

  if (!chips.length) return el("div");
  return el("div", { class: "flex flex-wrap items-center gap-2" }, chips);
}

function chip(label, onRemove) {
  return el(
    "button",
    {
      type: "button",
      class:
        "inline-flex items-center gap-1 rounded-full bg-brand-50 px-2.5 py-1 text-xs font-medium text-brand-700 hover:bg-brand-100",
      onClick: onRemove,
    },
    [label, el("span", { "aria-hidden": "true", class: "text-brand-400" }, "×")],
  );
}
