/**
 * Admin panel controller (admin.html).
 *
 * Sign-in only — there is no admin self-registration (brief/ARCHITECTURE:
 * admins are provisioned via `python -m app.seeds.create_admin`, an operator
 * action). Once signed in as an admin, renders a tabbed dashboard; each tab is
 * its own module under `js/admin/`, loaded lazily on first click.
 */
import { el, mount } from "../util/dom.js";
import { api, ApiError } from "../api/client.js";
import { restoreSession, getUser, isLoggedIn, login, logout } from "../auth.js";

const TABS = [
  { id: "moderation", label: "Moderation", load: () => import("../admin/moderation.js").then((m) => m.renderModeration) },
  { id: "taxonomy", label: "Taxonomy", load: () => import("../admin/taxonomy.js").then((m) => m.renderTaxonomy) },
  { id: "sources", label: "Sources", load: () => import("../admin/sources.js").then((m) => m.renderSources) },
  { id: "jobs", label: "Jobs", load: () => import("../admin/jobsTab.js").then((m) => m.renderJobs) },
  { id: "users", label: "Users", load: () => import("../admin/usersTab.js").then((m) => m.renderUsers) },
  { id: "content", label: "Content", load: () => import("../admin/contentTab.js").then((m) => m.renderContent) },
  { id: "analytics", label: "Analytics", load: () => import("../admin/analyticsTab.js").then((m) => m.renderAnalytics) },
];

export async function initAdminPage() {
  const root = document.getElementById("admin-root");
  await restoreSession();

  if (isLoggedIn() && getUser().role === "admin") {
    mount(root, dashboard());
  } else if (isLoggedIn()) {
    mount(
      root,
      el("div", { class: "mx-auto max-w-md rounded-card border border-amber-200 bg-amber-50 p-6 text-center" }, [
        el("p", { class: "font-medium text-amber-800" }, "You're signed in with a non-admin account."),
        el("button", { type: "button", class: "btn-ghost mt-4", onClick: async () => { await logout(); location.reload(); } }, "Sign out"),
      ]),
    );
  } else {
    mount(root, signInForm());
  }
}

function signInForm() {
  const email = el("input", { type: "email", required: true, class: "w-full rounded-lg border border-slate-300 px-3 py-2" });
  const password = el("input", { type: "password", required: true, class: "w-full rounded-lg border border-slate-300 px-3 py-2" });
  const errorSlot = el("div", {});
  const submitBtn = el("button", { type: "submit", class: "btn-primary w-full" }, "Sign in");

  const form = el(
    "form",
    {
      class: "space-y-4",
      onSubmit: async (e) => {
        e.preventDefault();
        submitBtn.disabled = true;
        try {
          const user = await login(email.value.trim(), password.value);
          if (user.role !== "admin") {
            mount(errorSlot, el("p", { class: "text-sm text-red-700" }, "This account is not an admin."));
            await logout();
            return;
          }
          initAdminPage();
        } catch (err) {
          const msg = err instanceof ApiError ? err.message : "Sign-in failed.";
          mount(errorSlot, el("p", { class: "rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700" }, msg));
        } finally {
          submitBtn.disabled = false;
        }
      },
    },
    [
      el("label", { class: "block text-sm" }, [el("span", { class: "mb-1 block font-medium text-ink-700" }, "Admin email"), email]),
      el("label", { class: "block text-sm" }, [el("span", { class: "mb-1 block font-medium text-ink-700" }, "Password"), password]),
      errorSlot,
      submitBtn,
    ],
  );

  return el("div", { class: "mx-auto max-w-sm rounded-card border border-slate-200 bg-white p-6 shadow-card" }, [
    el("h1", { class: "mb-5 text-xl font-bold text-ink-900" }, "Admin sign in"),
    form,
  ]);
}

function dashboard() {
  const user = getUser();
  const tabBar = el("div", { class: "mb-6 flex flex-wrap gap-1 border-b border-slate-200" });
  const content = el("div", {});
  let active = TABS[0].id;

  function renderTabBar() {
    mount(
      tabBar,
      TABS.map((t) =>
        el(
          "button",
          {
            type: "button",
            class: `border-b-2 px-3 py-2 text-sm font-medium ${
              t.id === active ? "border-brand-500 text-brand-600" : "border-transparent text-ink-500 hover:text-ink-800"
            }`,
            onClick: () => selectTab(t.id),
          },
          t.label,
        ),
      ),
    );
  }

  async function selectTab(id) {
    active = id;
    renderTabBar();
    mount(content, el("p", { class: "py-6 text-center text-sm text-ink-500" }, "Loading…"));
    const tab = TABS.find((t) => t.id === id);
    const renderFn = await tab.load();
    await renderFn(content);
  }

  renderTabBar();
  selectTab(active);

  return el("div", {}, [
    el("div", { class: "mb-4 flex items-center justify-between" }, [
      el("p", { class: "text-sm text-ink-500" }, `Signed in as ${user.email}`),
      el("button", { type: "button", class: "btn-ghost", onClick: async () => { await logout(); location.reload(); } }, "Sign out"),
    ]),
    tabBar,
    content,
  ]);
}
