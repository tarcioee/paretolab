// Building blocks of the screens: cards, counters, progress bars, switches, chips, tables.
import { api, h, toast } from "./dom.js";
import { errorText, t } from "./i18n.js";

export const card = (title, ...content) => h("div", { class: "card" }, title ? h("h2", {}, title) : null, ...content);

export const help = text => (text ? h("p", { class: "help" }, text) : null);

export function field(label, input, hint, { wide = false } = {}) {
  return h("div", { class: "field" + (wide ? " wide" : "") }, h("label", {}, label), input,
    hint ? h("div", { class: "help" }, hint) : null);
}

export function counter(value, label, { highlight = false, tone = "" } = {}) {
  return h("div", { class: "counter" + (highlight ? " highlight" : "") + (tone ? ` ${tone}` : "") },
    h("span", { class: "counter-value" }, value), h("span", { class: "counter-label" }, label));
}

export function progressBar(fraction, label) {
  const pct = Math.max(0, Math.min(100, 100 * (fraction || 0)));
  return h("div", { class: "progress", role: "progressbar", "aria-valuemin": "0", "aria-valuemax": "100",
    "aria-valuenow": pct.toFixed(0) },
  h("div", { class: "progress-fill", style: { width: `${pct}%` } }), h("span", { class: "progress-text" }, label));
}

export const miniBar = (fraction, failed = false) => h("div", { class: "mini-bar" + (failed ? " failed" : "") },
  h("div", { style: { width: `${Math.max(0, Math.min(100, 100 * (fraction || 0)))}%` } }));

export const badge = (text, tone = "") => h("span", { class: `badge ${tone}` }, text);

/** An on/off switch; `onchange(checked)`. */
export function switchInput(label, checked, onchange, { disabled = false } = {}) {
  return h("label", { class: "switch" + (disabled ? " disabled" : "") },
    h("input", { type: "checkbox", checked, disabled, onchange: e => onchange(e.target.checked) }),
    h("span", { class: "track" }), h("span", { class: "switch-label" }, label));
}

/** A selectable chip (a checkbox drawn as a pill). */
export function chip(label, checked, onchange, { title, disabled = false } = {}) {
  return h("label", { class: "chip", title },
    h("input", { type: "checkbox", checked, disabled, onchange: e => onchange(e.target.checked) }),
    h("span", {}, label));
}

export function table(headers, rows, { className = "tab", numeric = [] } = {}) {
  return h("div", { class: "scroll-x" }, h("table", { class: className },
    h("thead", {}, h("tr", {}, headers.map((x, i) => h("th", { class: numeric.includes(i) ? "num" : "" }, x)))),
    h("tbody", {}, rows.map(r => (r instanceof Node ? r : h("tr", {}, r.map((c, i) =>
      h("td", { class: numeric.includes(i) ? "num" : "" }, c))))))));
}

export function kv(pairs) {
  return h("dl", { class: "kv" }, pairs.filter(Boolean).map(([k, v]) => [h("dt", {}, k), h("dd", {}, v)]));
}

export async function openFolder(which) {
  try { await api("/api/open", { folder: which }); } catch (e) { toast(errorText(e), true); }
}

/** A path with a button that opens it in the file manager (`which`: setup, output or analysis). */
export function pathLine(label, path, which) {
  return h("div", { class: "path-line" }, h("span", { class: "path-label" }, label),
    h("code", { class: "path" }, path ?? "–"),
    which ? h("button", { type: "button", class: "link", onclick: () => openFolder(which) }, t("action.open_folder"))
      : null);
}

export function tabs(names, current, onpick) {
  return h("div", { class: "tabs", role: "tablist" }, names.map(([key, label]) => h("button", {
    type: "button", role: "tab", class: "tab" + (key === current ? " active" : ""),
    "aria-selected": String(key === current), onclick: () => onpick(key) }, label)));
}

export const alertBox = (text, tone = "info") => (text ? h("div", { class: `alert alert-${tone}`, role: tone === "error"
  ? "alert" : null }, text) : null);
