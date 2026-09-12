/**
 * Users tab: seekers + employers (view/disable/enable/reset password), and —
 * for a superadmin — the admin-account roster (brief: role-based access for
 * multiple admins).
 */
import { el, mount } from "../util/dom.js";
import { api, ApiError } from "../api/client.js";
import { table, pill, actionBtn, sectionTitle, errorNote } from "./shared.js";

export async function renderUsers(root) {
  mount(root, []);
  const listSlot = el("div", {});
  const adminsSlot = el("div", { class: "mt-8" });
  root.append(sectionTitle("Users"), listSlot, adminsSlot);

  async function loadUsers() {
    try {
      const rows = await api.adminListUsers({});
      mount(
        listSlot,
        table(["Email", "Role", "Status", "Last login", "Actions"], rows, (u) => [
          u.email,
          u.role,
          el("span", {}, [
            pill(u.is_active ? "active" : "hidden"),
            u.employer_account_status ? pill(u.employer_account_status) : null,
          ]),
          u.last_login_at ? new Date(u.last_login_at).toLocaleString() : "never",
          el("span", {}, [
            u.is_active
              ? actionBtn("Disable", async () => { await api.adminDisableUser(u.id); loadUsers(); }, { danger: true })
              : actionBtn("Enable", async () => { await api.adminEnableUser(u.id); loadUsers(); }),
            actionBtn("Reset password", async () => {
              const res = await api.adminResetPassword(u.id);
              window.alert(`Temporary password for ${u.email}:\n\n${res.temporary_password}\n\nShare this with the user out of band.`);
            }),
          ]),
        ]),
      );
    } catch (err) {
      mount(listSlot, errorNote(err));
    }
  }

  async function loadAdmins() {
    try {
      const admins = await api.adminListAdmins();
      const addBtn = actionBtn("+ Add admin", async () => {
        const email = window.prompt("New admin email:");
        if (!email) return;
        const password = window.prompt("Temporary password (min 8 chars):");
        if (!password) return;
        const role = window.prompt("Role (superadmin / moderator / editor / analyst):", "moderator");
        try {
          await api.adminCreateAdmin({ email, password, admin_role: role });
          loadAdmins();
        } catch (err) {
          window.alert(err instanceof ApiError ? err.message : "Failed to create admin.");
        }
      });
      mount(adminsSlot, [
        el("h3", { class: "mb-2 font-semibold text-ink-800" }, "Admin accounts"),
        addBtn,
        table(["Email", "Role", "Status"], admins, (a) => [a.email, a.admin_role, pill(a.is_active ? "active" : "hidden")]),
      ]);
    } catch {
      // 403 for non-superadmins — this section simply doesn't render for them.
    }
  }

  await Promise.all([loadUsers(), loadAdmins()]);
}
