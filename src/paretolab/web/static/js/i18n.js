// Translations. Texts live in /static/i18n/<language>.json; English is the fallback for anything missing.
// A text may use {name} placeholders, and {T:variants} for the word the project uses (manifest ui.terms).
// A text that depends on a count is {"one": ..., "other": ...}, chosen by the `n` argument.

const dictionaries = {};
let language = "en";
let terms = {};

export async function loadLanguage(lang) {
  for (const code of new Set(["en", lang])) {
    if (dictionaries[code]) continue;
    const response = await fetch(`/static/i18n/${code}.json`);
    dictionaries[code] = response.ok ? await response.json() : {};
  }
  language = dictionaries[lang] && Object.keys(dictionaries[lang]).length ? lang : "en";
  document.documentElement.lang = language;
  return language;
}

export const currentLanguage = () => language;
export const has = key => key in (dictionaries[language] ?? {}) || key in (dictionaries.en ?? {});

/** The manifest's own words (ui.terms). */
export function setTerms(projectTerms) { terms = projectTerms || {}; }

/** A text given as one string or as {language: string}: the current language, its base, English, or any. */
export function text(value) {
  if (value === null || value === undefined) return "";
  if (typeof value === "string") return value;
  const base = language.split("-")[0];
  return value[language] ?? value[base] ?? value.en ?? Object.values(value)[0] ?? "";
}

export function term(name) {
  if (terms[name] !== undefined) return text(terms[name]);
  if (name.endsWith("s") && terms[name.slice(0, -1)] !== undefined) {   // plural not given: derive it
    const one = text(terms[name.slice(0, -1)]);
    return /[sz]$/i.test(one) ? one : one + "s";
  }
  return t(`term.${name}`);
}

/** "1 instance", "3 instances": a number and the project's word for it, singular or plural. */
export const count = (n, name) => `${num(n)} ${n === 1 ? term(name) : term(`${name}s`)}`;

export const cap = s => (s ? s.charAt(0).toLocaleUpperCase(language) + s.slice(1) : s);

function show(value) {
  if (Array.isArray(value)) return value.map(show).join(", ");
  if (typeof value === "number") return num(value);
  if (value && typeof value === "object") return JSON.stringify(value);
  return value === null || value === undefined ? "" : String(value);
}

export function t(key, args = {}) {
  let value = dictionaries[language]?.[key] ?? dictionaries.en?.[key];
  if (value === undefined) return key;
  if (typeof value === "object") {
    const n = args.n ?? args.count ?? 0;
    const form = new Intl.PluralRules(language).select(n);
    value = value[form] ?? value.other;
  }
  return value
    .replace(/\{T:(\w+)\}/g, (_, name) => term(name))
    .replace(/\{Tc:(\w+)\}/g, (_, name) => cap(term(name)))
    .replace(/\{(\w+)\}/g, (all, name) => (name in args ? show(args[name]) : all));
}

// ------------------------------------------------------------------ numbers, times, dates

export function num(x, digits = 4) {
  if (x === null || x === undefined || Number.isNaN(x)) return "–";
  if (typeof x !== "number") return String(x);
  if (Number.isInteger(x)) return x.toLocaleString(language);
  if (x !== 0 && (Math.abs(x) < 1e-3 || Math.abs(x) >= 1e7)) return x.toExponential(2);
  return x.toLocaleString(language, { maximumSignificantDigits: digits });
}

export const pvalue = p => (p === null || p === undefined ? "–" : p < 1e-4 ? p.toExponential(1) :
  p.toLocaleString(language, { maximumFractionDigits: 4, minimumFractionDigits: 4 }));

export function duration(seconds) {
  if (seconds === null || seconds === undefined || Number.isNaN(seconds)) return "–";
  if (seconds < 9.95 && seconds > 0 && !Number.isInteger(seconds))
    return t("time.s", { s: seconds.toLocaleString(language, { maximumFractionDigits: 1 }) });
  const s = Math.round(seconds);
  const hh = Math.floor(s / 3600), mm = Math.floor((s % 3600) / 60), ss = s % 60;
  if (hh >= 48) return t("time.days", { d: Math.floor(hh / 24), h: hh % 24 });
  if (hh) return t("time.hm", { h: hh, m: String(mm).padStart(2, "0") });
  if (mm) return t("time.ms", { m: mm, s: String(ss).padStart(2, "0") });
  return t("time.s", { s: ss });
}

export const when = iso => (iso ? new Date(iso).toLocaleString(language) : "–");

// ------------------------------------------------------------------ messages from the server

/** A message {code, args, prefix, text} written by paretolab: translated when its code is known. */
export function msg(m) {
  if (!m) return "";
  if (typeof m === "string") return m;
  const key = m.code ? `msg.${m.code}` : null;
  if (!key || !has(key)) return m.text ?? "";
  const body = t(key, m.args || {});
  if (!m.prefix) return body;
  const prefix = has(`field.${m.prefix}`) ? t(`field.${m.prefix}`) : m.prefix;
  return `${prefix}: ${body}`;
}

/** An error thrown by api(): translated when the server gave a known code. */
export const errorText = e => (e?.code && has(`err.${e.code}`) ? t(`err.${e.code}`, e.args || {}) : e?.message ?? String(e));
