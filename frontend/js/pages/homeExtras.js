/**
 * Homepage-only extras that sit above the shared results view: the big hero
 * search box and the "popular categories" quick links. Both just write filter
 * state to the URL, which the search page picks up.
 */
import { api } from "../api/client.js";
import { el, mount } from "../util/dom.js";
import { readFilters, writeFilters } from "../util/url.js";
import { searchBar } from "../components/searchBar.js";

export async function mountHomeExtras() {
  const heroMount = document.getElementById("hero-search");
  const catsMount = document.getElementById("popular-categories");
  if (heroMount) {
    mount(
      heroMount,
      searchBar({
        value: readFilters().q || "",
        size: "hero",
        onSearch: (q) => {
          writeFilters({ ...readFilters(), q: q || undefined, page: 1 });
          document.getElementById("results")?.scrollIntoView({ behavior: "smooth", block: "start" });
        },
      }),
    );
  }

  if (catsMount) {
    try {
      const tree = await api.taxonomy();
      // Show the first handful of fields as quick filters.
      const links = tree.fields.slice(0, 7).map((f) =>
        el(
          "button",
          {
            type: "button",
            class:
              "rounded-full border border-slate-300 bg-white px-3 py-1 text-ink-700 hover:border-brand-300 hover:text-brand-600",
            onClick: () => {
              writeFilters({ field: [f.slug], page: 1 });
              document.getElementById("results")?.scrollIntoView({ behavior: "smooth" });
            },
          },
          f.name,
        ),
      );
      mount(catsMount, [el("span", { class: "text-ink-400" }, "Popular:"), ...links]);
    } catch {
      /* no categories yet — fine */
    }
  }
}
