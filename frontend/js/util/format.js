/**
 * Presentation formatters — salary, dates, misc labels.
 * Pure functions, no DOM.
 */

const CURRENCY_SYMBOL = { USD: "$", GBP: "£", EUR: "€", INR: "₹", CAD: "C$", AUD: "A$", BRL: "R$" };
const PERIOD_LABEL = { year: "/yr", month: "/mo", week: "/wk", day: "/day", hour: "/hr" };

/**
 * Format a salary object from the API (or return the "not disclosed" string).
 * @param {{min:?string,max:?string,currency:?string,period:?string}|null} salary
 */
export function formatSalary(salary) {
  if (!salary || (salary.min == null && salary.max == null)) return "Not disclosed";
  const sym = CURRENCY_SYMBOL[salary.currency] || (salary.currency ? salary.currency + " " : "");
  const per = PERIOD_LABEL[salary.period] || "";
  const n = (v) => {
    const num = Number(v);
    if (!isFinite(num)) return v;
    // 120000 -> "120k", 95500 -> "95.5k", 45 -> "45"
    if (num >= 1000) {
      const k = num / 1000;
      return (Number.isInteger(k) ? k : k.toFixed(1)) + "k";
    }
    return String(num);
  };
  const lo = salary.min != null ? n(salary.min) : null;
  const hi = salary.max != null ? n(salary.max) : null;
  const range = lo && hi && lo !== hi ? `${lo}–${hi}` : lo || hi;
  return `${sym}${range}${per}`;
}

/** Relative "time ago" from an ISO timestamp. */
export function timeAgo(iso) {
  if (!iso) return "";
  const then = new Date(iso).getTime();
  const secs = Math.max(1, Math.floor((Date.now() - then) / 1000));
  const units = [
    ["year", 31536000],
    ["month", 2592000],
    ["week", 604800],
    ["day", 86400],
    ["hour", 3600],
    ["minute", 60],
  ];
  for (const [name, size] of units) {
    const v = Math.floor(secs / size);
    if (v >= 1) return v === 1 ? `1 ${name} ago` : `${v} ${name}s ago`;
  }
  return "just now";
}

/** Title-case a snake_case enum value ("full_time" -> "Full time"). */
export function humanizeEnum(value) {
  return String(value || "")
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

/** Company initials for the logo fallback. */
export function initials(name) {
  return String(name || "?")
    .split(/\s+/)
    .slice(0, 2)
    .map((w) => w[0]?.toUpperCase() || "")
    .join("");
}
