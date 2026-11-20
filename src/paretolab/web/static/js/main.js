// paretolab web interface: three steps (setup, run, analysis) driven by the project manifest.
// Every label comes from /static/i18n/<language>.json or from the manifest; nothing here knows the problem.
import { loadAnalysis, renderAnalysis } from "./analysis.js";
import { $, $$, api, fill, h, interacting, store, toast, whenIdle } from "./dom.js";
import { errorText, loadLanguage, setTerms, t, text } from "./i18n.js";
import { phaseLabel, renderRun } from "./run.js";
import { loadSetupInfo, renderBar, renderSetup } from "./setup.js";
import { analyzing, emit, on, phase, S } from "./state.js";

const STEPS = ["setup", "run", "analysis"];
let pollTimer;
let wasAnalysing = false;
let userPicked = false;
let lastBusy = "";
let autoShown = false;

// ------------------------------------------------------------------ header

let headerKey = "";
function renderHeader(force = false) {
  const key = JSON.stringify([S.step, document.documentElement.lang, phaseLabel(), !!S.status, S.project?.icon]);
  if (!force && key === headerKey) return;
  headerKey = key;
  const m = S.manifest;
  const ui = m?.ui ?? {};
  const title = text(ui.title) || m?.name || "paretolab";
  const subtitle = text(ui.subtitle) || text(m?.description) || t("app.tagline");
  document.title = m ? `${title} · paretolab` : "paretolab";
  const icon = S.project?.icon ? h("img", { src: S.project.icon, alt: "", class: "brand-icon" }) : null;
  const p = phaseLabel();
  const languages = S.meta?.languages ?? { en: "English" };
  fill($("#header"), h("div", { class: "header-inner" },
    h("div", { class: "brand" }, icon, h("div", {}, h("h1", {}, title), h("p", {}, subtitle))),
    h("nav", { class: "steps", "aria-label": t("app.steps") }, STEPS.map((s, i) => h("button", { type: "button",
      class: "step" + (S.step === s ? " active" : ""), "aria-current": S.step === s ? "step" : null,
      onclick: () => { userPicked = true; goto(s); } }, `${i + 1} · ${t(`step.${s}`)}`))),
    h("div", { class: "header-side" },
      S.status ? h("span", { class: `badge ${p.tone} on-dark` }, p.text) : null,
      h("label", { class: "lang" }, h("span", { class: "sr-only" }, t("app.language")),
        h("select", { "aria-label": t("app.language"), onchange: e => setLanguage(e.target.value) },
          Object.entries(languages).map(([code, name]) => h("option", { value: code, selected: code === document.documentElement.lang }, name)))))));
  const accent = ui.accent;
  if (accent) document.documentElement.style.setProperty("--accent", accent);
}

async function setLanguage(lang) {
  store("paretolab.lang", lang);
  await loadLanguage(lang);
  document.activeElement?.blur();
  renderAll(true);
}

// ------------------------------------------------------------------ steps

function goto(step) {
  if (!STEPS.includes(step)) return;
  S.step = step;
  for (const s of STEPS) $(`#step-${s}`).hidden = s !== step;
  renderHeader();
  if (step === "run") renderRun(true);
  if (step === "analysis") loadAnalysis();
  window.scrollTo(0, 0);
}

function renderAll(force = false) {
  renderHeader(force);
  renderSetup();
  renderRun(force);
  renderAnalysis();
}

/** The step that matches the experiment: running → run, done → analysis, nothing yet → setup. */
function naturalStep() {
  const p = phase();
  if (p === "none") return "setup";
  if (p === "done" && !S.status.alive) return "analysis";
  return "run";
}

// ------------------------------------------------------------------ polling

async function poll() {
  clearTimeout(pollTimer);
  try {
    const before = phase();
    S.status = await api("/api/status");
    const after = phase();
    whenIdle(() => {
      renderHeader();
      if (S.step === "run" && !interacting()) renderRun();
    });
    const busyNow = `${!!S.status.alive}/${analyzing()}`;
    if (S.step === "setup" && busyNow !== lastBusy) renderBar();
    lastBusy = busyNow;
    const nowAnalysing = analyzing();
    if (wasAnalysing && !nowAnalysing) {
      const code = S.status.children.analyze.exit_code;
      toast(code === 0 ? t("an.finished_toast") : t("an.failed_toast", { code }), code !== 0);
      loadAnalysis(true);
    }
    wasAnalysing = nowAnalysing;
    if (before !== after && after === "done") loadAnalysis(true);
    // when a run followed here ends (and its analysis with it), show the analysis, unless the user moved away
    if (S.step === "run" && !userPicked && !autoShown && after === "done" && !S.status.alive && !nowAnalysing &&
        before !== "none") {
      autoShown = true;
      loadAnalysis(true);
      setTimeout(() => { if (S.step === "run" && !userPicked) goto("analysis"); }, 1200);
    }
    if (S.step === "analysis" && after === "done") loadAnalysis();
    $("#offline").hidden = true;
  } catch {
    $("#offline").hidden = false;
  }
  if (!S.meta?.tuner || S.meta.tuner.checking) refreshMeta();
  pollTimer = setTimeout(poll, S.status?.alive || analyzing() ? 1500 : 4000);
}

async function refreshMeta() {
  try {
    S.meta = await api("/api/meta");
    if (S.step === "setup" && S.draft?.tuning?.enabled && !S.meta.tuner.checking) renderSetup();
  } catch { /* the next poll tries again */ }
}

on("goto", step => { userPicked = true; goto(step); });
on("show", step => { userPicked = false; autoShown = false; goto(step); });
on("poll-soon", () => { clearTimeout(pollTimer); pollTimer = setTimeout(poll, 300); });
on("analysis-started", () => { wasAnalysing = true; emit("poll-soon"); });
on("saved", () => emit("poll-soon"));

// ------------------------------------------------------------------ start

async function main() {
  try {
    S.meta = await api("/api/meta");
  } catch { S.meta = null; }
  await loadLanguage(store("paretolab.lang") || S.meta?.language || "en");
  window.addEventListener("beforeunload", e => {
    if (S.draft && JSON.stringify(S.draft) !== JSON.stringify(S.saved)) e.preventDefault();
  });
  try {
    S.project = await api("/api/project");
  } catch (e) {
    renderHeader();
    $("#fatal").hidden = false;
    $("#fatal").textContent = `${t("app.no_project")}\n${errorText(e)}`;
    return;
  }
  S.manifest = S.project.manifest;
  setTerms(S.manifest.ui?.terms);
  loadSetupInfo(await api("/api/setup"));
  await poll();
  goto(naturalStep());
  renderAll();
  for (const el of $$("[data-hidden-until-ready]")) el.removeAttribute("data-hidden-until-ready");
}

main();
