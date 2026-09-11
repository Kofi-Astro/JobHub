/**
 * Taxonomy tab: fields/sub-fields tree with inline create/rename/deactivate,
 * remap-then-delete, and the uncategorized-jobs review queue.
 */
import { el, mount } from "../util/dom.js";
import { api } from "../api/client.js";
import { table, actionBtn, sectionTitle, errorNote } from "./shared.js";

export async function renderTaxonomy(root) {
  mount(root, []);
  const treeSlot = el("div", { class: "space-y-3" });
  const queueSlot = el("div", {});
  root.append(
    sectionTitle("Taxonomy"),
    el(
      "button",
      {
        type: "button",
        class: "btn-ghost mb-3",
        onClick: async () => {
          const name = window.prompt("New field name:");
          if (!name) return;
          const slug = name.toLowerCase().trim().replace(/[^a-z0-9]+/g, "-");
          await api.adminCreateField({ slug, name });
          load();
        },
      },
      "+ Add field",
    ),
    treeSlot,
    el("h3", { class: "mb-2 mt-8 font-semibold text-ink-800" }, "Uncategorized jobs (needs manual review)"),
    queueSlot,
  );

  async function load() {
    try {
      const fields = await api.adminTaxonomy();
      mount(treeSlot, fields.map((f) => fieldCard(f, load)));
    } catch (err) {
      mount(treeSlot, errorNote(err));
    }
  }

  async function loadQueue() {
    try {
      const page = await api.adminUncategorized({ page_size: 25 });
      const fields = await api.adminTaxonomy();
      mount(
        queueSlot,
        table(["Title", "Company", "Origin", "Categorize"], page.items, (j) => [
          j.title,
          j.company_name,
          j.origin,
          categorizePicker(j, fields, loadQueue),
        ]),
      );
      if (page.total > page.items.length) {
        queueSlot.append(
          el("p", { class: "mt-2 text-xs text-ink-400" }, `Showing ${page.items.length} of ${page.total}.`),
        );
      }
    } catch (err) {
      mount(queueSlot, errorNote(err));
    }
  }

  await load();
  await loadQueue();
}

function fieldCard(field, reload) {
  const subRows = field.subfields.map((sf) =>
    el("div", { class: "flex items-center justify-between border-t border-slate-100 py-1.5 pl-4 text-sm" }, [
      el("span", { class: sf.is_active ? "" : "text-ink-400 line-through" }, `${sf.name} (${sf.job_count})`),
      el("span", {}, [
        actionBtn(sf.is_active ? "Deactivate" : "Activate", async () => {
          await api.adminUpdateSubfield(sf.id, { is_active: !sf.is_active });
          reload();
        }),
        actionBtn(
          "Delete",
          async () => {
            if (sf.job_count > 0) {
              window.alert(`${sf.job_count} job(s) use this sub-field — remap them first (use another sub-field's "Delete" only once its count is 0, after moving jobs via the API).`);
              return;
            }
            await api.adminDeleteSubfield(sf.id);
            reload();
          },
          { danger: true },
        ),
      ]),
    ]),
  );

  return el("div", { class: "rounded-card border border-slate-200 bg-white p-4" }, [
    el("div", { class: "flex items-center justify-between" }, [
      el("span", { class: `font-semibold ${field.is_active ? "text-ink-900" : "text-ink-400 line-through"}` }, field.name),
      el("span", {}, [
        actionBtn(field.is_active ? "Deactivate" : "Activate", async () => {
          await api.adminUpdateField(field.id, { is_active: !field.is_active });
          reload();
        }),
        actionBtn("+ Sub-field", async () => {
          const name = window.prompt(`New sub-field under "${field.name}":`);
          if (!name) return;
          const slug = name.toLowerCase().trim().replace(/[^a-z0-9]+/g, "-");
          await api.adminCreateSubfield({ field_id: field.id, slug, name });
          reload();
        }),
      ]),
    ]),
    ...subRows,
  ]);
}

function categorizePicker(job, fields, reload) {
  const fieldSelect = el(
    "select",
    { class: "rounded border border-slate-300 px-1 py-0.5 text-xs" },
    fields.map((f) => el("option", { value: f.slug }, f.name)),
  );
  const subSelect = el("select", { class: "ml-1 rounded border border-slate-300 px-1 py-0.5 text-xs" });
  const populate = () => {
    const f = fields.find((x) => x.slug === fieldSelect.value);
    mount(subSelect, (f?.subfields || []).map((s) => el("option", { value: s.slug }, s.name)));
  };
  fieldSelect.addEventListener("change", populate);
  populate();

  const applyBtn = actionBtn("Set", async () => {
    await api.adminCategorizeJob(job.id, { field_slug: fieldSelect.value, subfield_slug: subSelect.value });
    reload();
  });

  return el("span", { class: "inline-flex items-center" }, [fieldSelect, subSelect, applyBtn]);
}
