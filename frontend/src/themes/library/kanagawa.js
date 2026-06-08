// themes/library/kanagawa.js
import GreatWaveCanvas from "../GreatWaveCanvas.jsx";

export default {
  id: "kanagawa",
  name: "Kanagawa",
  desc: "The Great Wave · ukiyo-e",
  order: 18,
  preview: ["#ece2cb", "#faf5e9", "#1c5d8c"],
  // The curling Great Wave with foam claws, built for a LIGHT background.
  overlay: GreatWaveCanvas,
  vars: {
    "--bg0": "#ece2cb", "--bg1": "#faf5e9", "--bg2": "#e4d8bd", "--bg3": "#d8c9a8", "--bg4": "#c6b48a",
    "--border": "rgba(20,50,80,0.1)", "--border2": "rgba(20,50,80,0.16)", "--border3": "rgba(20,50,80,0.26)",
    "--t0": "#122c44", "--t1": "#41617e", "--t2": "#8295a8",
    "--accent": "#1c5d8c", "--accent2": "#2e7ab0", "--accent3": "rgba(28,93,140,0.1)",
    "--cyan": "#0891b2", "--green": "#3f7d4f", "--red": "#b03a2e", "--yellow": "#c08a2e", "--purple": "#5b5b8a", "--pink": "#a85676",
    "--sans": "'DM Sans',sans-serif", "--mono": "'JetBrains Mono',monospace",
    "--r": "8px", "--rl": "12px",
  },
};
