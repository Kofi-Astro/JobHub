/**
 * Moderation tab: pending employer accounts + pending employer job postings —
 * the queue that makes the brief's "flag new employer accounts and/or
 * first-time postings for approval" concrete.
 */
import { el, mount } from "../util/dom.js";
import { api } from "../api/client.js";
import { table, actionBtn, promptReason, sectionTitle, errorNote } from "./shared.js";

export async function renderModeration(root) {
  mount(root, [sectionTitle("Moderation queue")]);
  const employersSlot = el("div", { class: "mb-8" });
  const jobsSlot = el("div", {});
  root.append(
    el("h3", { class: "mb-2 font-semibold text-ink-800" }, "Pending employer accounts"),
    employersSlot,
    el("h3", { class: "mb-2 mt-8 font-semibold text-ink-800" }, "Pending job postings"),
    jobsSlot,
  );

  async function loadEmployers() {
    try {
      const rows = await api.adminPendingEmployers();
      mount(
        employersSlot,
        table(["Company", "Contact", "Applied", "Actions"], rows, (r) => [
          r.company_name,
          `${r.full_name || "—"} · ${r.email}`,
          new Date(r.created_at).toLocaleDateString(),
          el("span", {}, [
            actionBtn("Approve", async () => {
              await api.adminApproveEmployer(r.user_id);
              loadEmployers();
            }),
            actionBtn(
              "Reject",
              async () => {
                const reason = promptReason("Reason for rejecting this employer account:");
                if (!reason) return;
                await api.adminRejectEmployer(r.user_id, reason);
                loadEmployers();
              },
              { danger: true },
            ),
          ]),
        ]),
      );
    } catch (err) {
      mount(employersSlot, errorNote(err));
    }
  }

  async function loadJobs() {
    try {
      const rows = await api.adminPendingJobs();
      mount(
        jobsSlot,
        table(["Title", "Company", "Employer", "Actions"], rows, (r) => [
          r.title,
          r.company_name,
          r.employer_email,
          el("span", {}, [
            actionBtn("Approve", async () => {
              await api.adminApproveJob(r.id);
              loadJobs();
            }),
            actionBtn(
              "Reject",
              async () => {
                const reason = promptReason("Reason for rejecting this posting:");
                if (!reason) return;
                await api.adminRejectJob(r.id, reason);
                loadJobs();
              },
              { danger: true },
            ),
          ]),
        ]),
      );
    } catch (err) {
      mount(jobsSlot, errorNote(err));
    }
  }

  await Promise.all([loadEmployers(), loadJobs()]);
}
