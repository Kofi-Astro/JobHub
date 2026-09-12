/**
 * General job management: search/filter any listing, edit its title, hide it
 * (spam, a bad scrape, a legal request) or restore it (brief: "manually edit/
 * hide/unpublish any listing, aggregated or employer-posted").
 */
import { el, mount } from "../util/dom.js";
import { api } from "../api/client.js";
import { table, pill, actionBtn, sectionTitle, errorNote } from "./shared.js";

export async function renderJobs(root) {
  mount(root, []);
  const statusSelect = el(
    "select",
    { class: "rounded-lg border border-slate-300 px-2 py-1.5 text-sm" },
    ["", "active", "pending", "rejected", "closed", "expired", "hidden"].map((s) =>
      el("option", { value: s }, s || "All statuses"),
    ),
  );
  const qInput = el("input", {
    type: "search",
    placeholder: "Search title…",
    class: "rounded-lg border border-slate-300 px-2 py-1.5 text-sm",
  });
  const searchBtn = actionBtn("Search", () => load());
  const listSlot = el("div", {});

  root.append(
    sectionTitle("All jobs"),
    el("div", { class: "mb-3 flex flex-wrap items-center gap-2" }, [statusSelect, qInput, searchBtn]),
    listSlot,
  );

  async function load() {
    try {
      const page = await api.adminListJobs({
        status: statusSelect.value || undefined,
        q: qInput.value.trim() || undefined,
        page_size: 50,
      });
      mount(
        listSlot,
        table(["Title", "Company", "Origin", "Status", "Views/Clicks", "Actions"], page.items, (j) => [
          el(
            "button",
            {
              type: "button",
              class: "text-left text-brand-600 hover:underline",
              onClick: () => {
                const title = window.prompt("Edit title:", j.title);
                if (title && title !== j.title) {
                  api.adminUpdateJob(j.id, { title }).then(load);
                }
              },
            },
            j.title,
          ),
          j.company_name,
          j.origin,
          pill(j.status),
          `${j.view_count} / ${j.apply_click_count}`,
          j.status === "hidden"
            ? actionBtn("Unhide", async () => { await api.adminUnhideJob(j.id); load(); })
            : actionBtn("Hide", async () => { await api.adminHideJob(j.id); load(); }, { danger: true }),
        ]),
      );
      listSlot.append(el("p", { class: "mt-2 text-xs text-ink-400" }, `${page.total} total.`));
    } catch (err) {
      mount(listSlot, errorNote(err));
    }
  }

  await load();
}
