/** Loading placeholders — shown while a request is in flight so the layout
 * doesn't jump and the page feels responsive. */
import { el } from "../util/dom.js";

export function jobCardSkeleton() {
  const bar = (w) => el("div", { class: `h-3 rounded bg-slate-200 ${w}` });
  return el("div", { class: "job-card animate-pulse" }, [
    el("div", { class: "flex items-start gap-3" }, [
      el("div", { class: "h-10 w-10 rounded-lg bg-slate-200" }),
      el("div", { class: "flex-1 space-y-2" }, [
        bar("w-2/3"),
        bar("w-1/3"),
        el("div", { class: "flex gap-2 pt-1" }, [bar("w-20"), bar("w-16"), bar("w-24")]),
      ]),
    ]),
  ]);
}

export function skeletonList(n = 6) {
  return Array.from({ length: n }, jobCardSkeleton);
}
