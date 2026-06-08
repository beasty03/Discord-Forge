// themes/library/aurora.js
import AuroraCanvas from "../AuroraCanvas.jsx";

export default {
  id: "aurora",
  name: "Aurora",
  desc: "Midnight navy · borealis",
  order: 14,
  preview: ["#07101e", "#0a1320", "#2dd4bf"],
  overlay: AuroraCanvas,
  vars: {
    "--bg0": "#07101e", "--bg1": "#0a1320", "--bg2": "#0e1a2b", "--bg3": "#142337", "--bg4": "#1c2f47",
    "--border": "rgba(100,200,180,0.1)", "--border2": "rgba(100,200,180,0.18)", "--border3": "rgba(100,200,180,0.3)",
    "--t0": "#e6f1f0", "--t1": "#94aab2", "--t2": "#4f6670",
    "--accent": "#2dd4bf", "--accent2": "#4ade80", "--accent3": "rgba(45,212,191,0.13)",
    "--cyan": "#22d3ee", "--green": "#4ade80", "--red": "#f87171", "--yellow": "#fbbf24", "--purple": "#a78bfa", "--pink": "#f472b6",
    "--sans": "'Plus Jakarta Sans',sans-serif", "--mono": "'JetBrains Mono',monospace",
    "--r": "12px", "--rl": "16px",
  },
};
