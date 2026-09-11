/**
 * The header auth slot: "Sign in" when anonymous, "Hi, {name} · Sign out"
 * when logged in. Mounted into a `#auth-nav` element present on every page's
 * header; re-renders itself on `authchange` so every open tab/page stays in
 * sync with a login or logout that just happened.
 */
import { el, mount } from "../util/dom.js";
import { getUser, isLoggedIn, logout, restoreSession } from "../auth.js";

export function mountAuthNav(container) {
  const render = () => mount(container, isLoggedIn() ? loggedInView() : loggedOutView());
  render();
  window.addEventListener("authchange", render);
  restoreSession().then(render);
}

function loggedOutView() {
  return el("a", { href: "account.html", class: "btn-ghost" }, "Sign in");
}

function loggedInView() {
  const user = getUser();
  return el("div", { class: "flex items-center gap-2 text-sm" }, [
    el("span", { class: "hidden text-ink-600 sm:inline" }, user.full_name || user.email),
    el(
      "button",
      {
        type: "button",
        class: "btn-ghost",
        onClick: async () => {
          await logout();
          window.location.href = "index.html";
        },
      },
      "Sign out",
    ),
  ]);
}
