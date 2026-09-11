/**
 * Job-seeker account page (account.html): sign in or create an account.
 *
 * This is deliberately seeker-only — employers get their own dedicated
 * registration inside the employer portal (milestone 10), matching the
 * brief's "separate, signposted entry point for employers" away from the
 * regular job-seeker experience.
 *
 * On success, redirects to `?next=` if present (so "sign in to save this job"
 * style links can return the user where they started), else the homepage.
 */
import { el, mount } from "../util/dom.js";
import { login, registerSeeker, restoreSession, isLoggedIn } from "../auth.js";
import { ApiError } from "../api/client.js";

export async function initAccountPage() {
  const root = document.getElementById("account-root");

  // Already signed in (valid refresh cookie) — nothing to do here.
  await restoreSession();
  if (isLoggedIn()) {
    redirectAfterAuth();
    return;
  }

  let mode = "login"; // or "register"
  const render = () => mount(root, mode === "login" ? loginForm(switchMode) : registerForm(switchMode));
  function switchMode(next) {
    mode = next;
    render();
  }
  render();
}

function redirectAfterAuth() {
  const next = new URLSearchParams(location.search).get("next");
  window.location.href = next || "index.html";
}

function errorBox(message) {
  return message
    ? el("p", { class: "rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700" }, message)
    : null;
}

function loginForm(switchMode) {
  let error = "";
  const emailInput = el("input", {
    type: "email", required: true, autocomplete: "email",
    class: "w-full rounded-lg border border-slate-300 px-3 py-2",
  });
  const passwordInput = el("input", {
    type: "password", required: true, autocomplete: "current-password",
    class: "w-full rounded-lg border border-slate-300 px-3 py-2",
  });
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
          await login(emailInput.value.trim(), passwordInput.value);
          redirectAfterAuth();
        } catch (err) {
          error = err instanceof ApiError ? err.message : "Something went wrong. Try again.";
          mount(errorSlot, errorBox(error));
        } finally {
          submitBtn.disabled = false;
        }
      },
    },
    [
      field("Email", emailInput),
      field("Password", passwordInput),
      errorSlot,
      submitBtn,
    ],
  );

  return card("Sign in", form, [
    "New to JobHub? ",
    el("button", { type: "button", class: "font-medium text-brand-600 hover:underline", onClick: () => switchMode("register") }, "Create an account"),
  ]);
}

function registerForm(switchMode) {
  const nameInput = el("input", { type: "text", autocomplete: "name", class: "w-full rounded-lg border border-slate-300 px-3 py-2" });
  const emailInput = el("input", { type: "email", required: true, autocomplete: "email", class: "w-full rounded-lg border border-slate-300 px-3 py-2" });
  const passwordInput = el("input", {
    type: "password", required: true, minlength: "8", autocomplete: "new-password",
    class: "w-full rounded-lg border border-slate-300 px-3 py-2",
  });
  const errorSlot = el("div", {});
  const submitBtn = el("button", { type: "submit", class: "btn-primary w-full" }, "Create account");

  const form = el(
    "form",
    {
      class: "space-y-4",
      onSubmit: async (e) => {
        e.preventDefault();
        submitBtn.disabled = true;
        try {
          await registerSeeker({
            email: emailInput.value.trim(),
            password: passwordInput.value,
            fullName: nameInput.value.trim() || undefined,
          });
          redirectAfterAuth();
        } catch (err) {
          const msg = err instanceof ApiError ? err.message : "Something went wrong. Try again.";
          mount(errorSlot, errorBox(msg));
        } finally {
          submitBtn.disabled = false;
        }
      },
    },
    [
      field("Full name (optional)", nameInput),
      field("Email", emailInput),
      field("Password", passwordInput, "At least 8 characters."),
      errorSlot,
      submitBtn,
    ],
  );

  return card("Create your account", form, [
    "Already have an account? ",
    el("button", { type: "button", class: "font-medium text-brand-600 hover:underline", onClick: () => switchMode("login") }, "Sign in"),
  ]);
}

function field(label, input, hint) {
  return el("label", { class: "block text-sm" }, [
    el("span", { class: "mb-1 block font-medium text-ink-700" }, label),
    input,
    hint && el("span", { class: "mt-1 block text-xs text-ink-400" }, hint),
  ]);
}

function card(title, form, footerParts) {
  return el("div", { class: "mx-auto max-w-sm rounded-card border border-slate-200 bg-white p-6 shadow-card" }, [
    el("h1", { class: "mb-5 text-xl font-bold text-ink-900" }, title),
    form,
    el("p", { class: "mt-5 text-center text-sm text-ink-500" }, footerParts),
  ]);
}
