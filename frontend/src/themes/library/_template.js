// themes/library/_template.js
//
// HOW TO ADD A THEME
// 1. Copy this file and rename it to <your-id>.js  (e.g. midnight.js)
// 2. Fill in the values below.
// 3. Save. It appears in the app automatically — no other file to touch.
//
// Files starting with "_" are ignored by the loader, so this template
// never shows up in the app itself.
//
// Required:  name, vars (every variable below must have a value)
// Optional:  desc, order (sort position in the picker), preview (3 swatches),
//            overlay (a React component drawn full-screen behind the UI)

// import MyOverlay from "../MyOverlay.jsx"; // optional ambient effect

export default {
  name: "My Theme",
  desc: "One-line description",
  order: 99,                                   // lower = earlier in the picker
  preview: ["#000000", "#111111", "#5b6cf9"],  // [background, surface, accent]

  // overlay: MyOverlay,                        // optional — adds animation AND marks theme as Pro-only

  vars: {
    // Background layers — bg0 is the page, bg1..bg4 step toward the foreground
    "--bg0": "", "--bg1": "", "--bg2": "", "--bg3": "", "--bg4": "",
    // Borders — subtle → strong
    "--border": "", "--border2": "", "--border3": "",
    // Text — primary → muted
    "--t0": "", "--t1": "", "--t2": "",
    // Accent + a translucent fill version of it
    "--accent": "", "--accent2": "", "--accent3": "",
    // Semantic colors
    "--cyan": "", "--green": "", "--red": "", "--yellow": "", "--purple": "", "--pink": "",
    // Fonts (make sure they're loaded — see the @import in App.jsx's CSS const)
    "--sans": "'Inter',sans-serif", "--mono": "'JetBrains Mono',monospace",
    // Corner radii — base and large
    "--r": "10px", "--rl": "14px",
  },
};
