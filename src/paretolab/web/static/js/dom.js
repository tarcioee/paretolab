// Small DOM and data helpers shared by every screen.

export const $ = (sel, el = document) => el.querySelector(sel);
export const $$ = (sel, el = document) => [...el.querySelectorAll(sel)];

/** h("div", {class: "x", onclick: f}, child, [children], "text") builds an element. */
export function h(tag, attrs = {}, ...children) {
  const svg = ["svg", "g", "path", "circle", "line", "rect", "polyline", "text", "defs", "linearGradient", "stop"]
    .includes(tag);
  const el = svg ? document.createElementNS("http://www.w3.org/2000/svg", tag) : document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === undefined || v === null || v === false) continue;
    if (k === "class") el.setAttribute("class", v);
    else if (k === "text") el.textContent = v;
    else if (k === "style" && typeof v === "object") Object.assign(el.style, v);
    else if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2), v);
    else if (!svg && k in el && typeof v !== "string") el[k] = v;
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat(Infinity)) if (c !== null && c !== undefined && c !== false)
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  return el;
}

/** Replaces the children of `el`, skipping null, undefined and false (replaceChildren would print them). */
export function fill(el, ...children) {
  el.replaceChildren(...children.flat(Infinity).filter(c => c !== null && c !== undefined && c !== false));
  return el;
}

export class ApiError extends Error {
  constructor(data, status) {
    super(data.error || `HTTP ${status}`);
    this.code = data.code || null;
    this.args = data.args || {};
    this.status = status;
  }
}

export async function api(path, body) {
  const options = body === undefined ? {} :
    { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
  const response = await fetch(path, options);
  let data;
  try { data = await response.json(); } catch { data = { error: `HTTP ${response.status}` }; }
  if (!response.ok) throw new ApiError(data, response.status);
  return data;
}

// ------------------------------------------------------------------ nested values of the draft setup

export function getp(obj, path) {
  return path.split(".").reduce((o, k) => (o === undefined || o === null ? undefined : o[k]), obj);
}

export function setp(obj, path, value) {
  const keys = path.split(".");
  const parents = [obj];
  let o = obj;
  for (const k of keys.slice(0, -1)) {
    if (typeof o[k] !== "object" || o[k] === null || Array.isArray(o[k])) o[k] = {};
    o = o[k];
    parents.push(o);
  }
  const last = keys[keys.length - 1];
  if (value === undefined) delete o[last]; else o[last] = value;
  for (let i = keys.length - 1; i > 0; i--) {            // drop objects left empty
    if (Object.keys(parents[i]).length === 0) delete parents[i - 1][keys[i - 1]]; else break;
  }
}

export const clone = x => (x === undefined ? undefined : JSON.parse(JSON.stringify(x)));
const stable = x => Array.isArray(x) ? x.map(stable) : (x && typeof x === "object")
  ? Object.fromEntries(Object.keys(x).sort().map(k => [k, stable(x[k])])) : x;
export const same = (a, b) => JSON.stringify(stable(a)) === JSON.stringify(stable(b));

export function store(key, value) {
  try {
    if (value === undefined) return localStorage.getItem(key);
    localStorage.setItem(key, value);
  } catch { /* private window or blocked storage: the page works without it */ }
  return null;
}

// ------------------------------------------------------------------ redrawing without getting in the way

let pointerDown = false;
const waiting = new Set();
document.addEventListener("pointerdown", () => { pointerDown = true; }, true);
document.addEventListener("pointerup", () => {
  pointerDown = false;
  setTimeout(() => { const jobs = [...waiting]; waiting.clear(); jobs.forEach(fn => fn()); }, 0);
}, true);

/** True while the user is clicking, or a field or list of the page has the focus. */
export function interacting() {
  const el = document.activeElement;
  return pointerDown || (!!el && ["INPUT", "SELECT", "TEXTAREA"].includes(el.tagName) && !el.closest("#modal"));
}

/** Runs `fn` now, or when the user lets go of the mouse; a redraw then never swallows a click. */
export function whenIdle(fn) {
  if (pointerDown) waiting.add(fn); else fn();
}

// ------------------------------------------------------------------ toast and dialog

let toastTimer;
export function toast(text, bad = false) {
  const t = $("#toast");
  t.textContent = text;
  t.className = "show" + (bad ? " bad" : "");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { t.className = ""; }, bad ? 8000 : 3500);
}

/** A modal dialog; resolves true when confirmed. `body` is a node; `ok` and `cancel` are button labels. */
export function confirmDialog({ title, body, ok, cancel, danger = false }) {
  return new Promise(resolve => {
    const box = $("#modal");
    const close = answer => { box.hidden = true; document.removeEventListener("keydown", key); resolve(answer); };
    const key = e => { if (e.key === "Escape") close(false); };
    const okButton = h("button", { type: "button", class: "btn " + (danger ? "btn-danger" : "btn-prim"),
      onclick: () => close(true) }, ok);
    box.replaceChildren(h("div", { class: "modal-box", role: "document" },
      h("h2", { id: "modal-title" }, title), body,
      h("div", { class: "buttons right" },
        h("button", { type: "button", class: "btn btn-sec", onclick: () => close(false) }, cancel), okButton)));
    box.hidden = false;
    box.onclick = e => { if (e.target === box) close(false); };
    document.addEventListener("keydown", key);
    okButton.focus();
  });
}
