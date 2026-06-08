// themes/index.js
// ─────────────────────────────────────────────────────────────
// Auto-loading theme library.
//
// To add a theme: copy ./library/_template.js, rename it to
// <your-id>.js, fill in the values. That's it — it shows up in
// THEMES, getThemeList() and the settings picker automatically.
// You never edit this file.
// ─────────────────────────────────────────────────────────────

const modules = import.meta.glob("./library/*.{js,jsx}", { eager: true });

function buildRegistry() {
  const themes = {};
  for (const path of Object.keys(modules)) {
    const file = path.split("/").pop();
    if (file.startsWith("_")) continue;

    const theme = modules[path]?.default;
    const id = theme?.id || file.replace(/\.[^.]+$/, "");

    if (!theme || !theme.vars) {
      console.warn(`[themes] "${path}" has no default export with a 'vars' map — skipped.`);
      continue;
    }
    if (themes[id]) {
      console.warn(`[themes] Duplicate theme id "${id}" (${path}) overwrote an earlier one.`);
    }
    themes[id] = { ...theme, id };
  }
  return themes;
}

/** All themes, keyed by id. Drop-in replacement for the old THEMES object. */
export const THEMES = buildRegistry();

/** Preferred default if present, otherwise the first registered theme. */
export const DEFAULT_THEME = THEMES.forge ? "forge" : Object.keys(THEMES)[0];

/** Look up a theme, falling back to the default for unknown ids. */
export function getTheme(id) {
  return THEMES[id] || THEMES[DEFAULT_THEME];
}

/** Themes as a sorted array (by optional `order`, then name) — use for the picker UI. */
export function getThemeList() {
  return Object.values(THEMES).sort(
    (a, b) => (a.order ?? 100) - (b.order ?? 100) || a.name.localeCompare(b.name)
  );
}

/** The :root{} CSS string for a theme. Same signature as before — drop-in compatible. */
export function getRootCSS(themeId) {
  const { vars } = getTheme(themeId);
  return `:root{${Object.entries(vars).map(([k, v]) => `${k}:${v}`).join(";")}}`;
}

/** A theme's optional full-screen overlay effect (a React component), or null. */
export function getOverlay(themeId) {
  return getTheme(themeId).overlay || null;
}

// Back-compat: existing `import { CherryBlossomCanvas }` keeps working.
export { default as CherryBlossomCanvas } from "./CherryBlossomCanvas.jsx";
