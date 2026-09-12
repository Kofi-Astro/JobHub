/**
 * Content tab: homepage/site content key-value blobs + announcement banners
 * (brief: "site content management — homepage featured categories,
 * banners/announcements").
 */
import { el, mount } from "../util/dom.js";
import { api, ApiError } from "../api/client.js";
import { table, pill, actionBtn, sectionTitle, errorNote } from "./shared.js";

export async function renderContent(root) {
  mount(root, []);
  const contentSlot = el("div", { class: "space-y-2" });
  const announcementsSlot = el("div", {});

  root.append(
    sectionTitle("Site content"),
    el(
      "button",
      {
        type: "button",
        class: "btn-ghost mb-3",
        onClick: async () => {
          const key = window.prompt('Content key (e.g. "homepage.featured_fields"):');
          if (!key) return;
          const raw = window.prompt("JSON value:", "[]");
          if (raw == null) return;
          try {
            await api.adminSetContent(key, JSON.parse(raw));
            loadContent();
          } catch {
            window.alert("That wasn't valid JSON.");
          }
        },
      },
      "+ Set a content key",
    ),
    contentSlot,
    el("h2", { class: "mb-3 mt-8 text-lg font-bold text-ink-900" }, "Announcements"),
    el(
      "button",
      {
        type: "button",
        class: "btn-ghost mb-3",
        onClick: async () => {
          const title = window.prompt("Announcement title:");
          if (!title) return;
          const body = window.prompt("Announcement body:");
          if (!body) return;
          await api.adminCreateAnnouncement({ title, body, is_active: true });
          loadAnnouncements();
        },
      },
      "+ New announcement",
    ),
    announcementsSlot,
  );

  async function loadContent() {
    try {
      const rows = await api.adminListContent();
      mount(
        contentSlot,
        table(["Key", "Value", "Updated"], rows, (c) => [
          c.key,
          el("code", { class: "text-xs" }, JSON.stringify(c.value)),
          new Date(c.updated_at).toLocaleString(),
        ]),
      );
    } catch (err) {
      mount(contentSlot, errorNote(err));
    }
  }

  async function loadAnnouncements() {
    try {
      const rows = await api.adminListAnnouncements();
      mount(
        announcementsSlot,
        table(["Title", "Status", "Level", "Actions"], rows, (a) => [
          a.title,
          pill(a.is_active ? "active" : "hidden"),
          a.level,
          el("span", {}, [
            actionBtn(a.is_active ? "Deactivate" : "Activate", async () => {
              try {
                await api.adminUpdateAnnouncement(a.id, { ...a, is_active: !a.is_active });
                loadAnnouncements();
              } catch (err) {
                window.alert(err instanceof ApiError ? err.message : "Update failed.");
              }
            }),
            actionBtn("Delete", async () => { await api.adminDeleteAnnouncement(a.id); loadAnnouncements(); }, { danger: true }),
          ]),
        ]),
      );
    } catch (err) {
      mount(announcementsSlot, errorNote(err));
    }
  }

  await Promise.all([loadContent(), loadAnnouncements()]);
}
