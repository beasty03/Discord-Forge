// themes/library/synthwave.js
import SynthwaveGridCanvas from "../SynthwaveGridCanvas.jsx";

export default {
  id: "synthwave",
  name: "Synthwave",
  desc: "Retro neon · outrun grid",
  order: 10,
  preview: ["#0a0612", "#120a1f", "#ff3d9a"],
  // The scrolling grid ships with the theme — switch to Synthwave and it appears.
  overlay: SynthwaveGridCanvas,
  vars: {
    "--bg0": "#0a0612", "--bg1": "#120a1f", "--bg2": "#18102b", "--bg3": "#221638", "--bg4": "#2e1d4c",
    "--border": "rgba(214,120,255,0.12)", "--border2": "rgba(214,120,255,0.22)", "--border3": "rgba(214,120,255,0.36)",
    "--t0": "#f4ecff", "--t1": "#b39fd6", "--t2": "#6b5a8f",
    "--accent": "#ff3d9a", "--accent2": "#ff7ac6", "--accent3": "rgba(255,61,154,0.14)",
    "--cyan": "#22d3ee", "--green": "#34d399", "--red": "#ff4d6d", "--yellow": "#ffd23f", "--purple": "#c084fc", "--pink": "#ff7ac6",
    "--sans": "'Plus Jakarta Sans',sans-serif", "--mono": "'JetBrains Mono',monospace",
    "--r": "8px", "--rl": "12px",
  },
};
