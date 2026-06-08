// themes/library/lumen.js
import FirefliesCanvas from "../FirefliesCanvas.jsx";

export default {
  id: "lumen",
  name: "Lumen",
  desc: "Deep forest · fireflies",
  order: 16,
  preview: ["#07140d", "#0b1a11", "#a3e635"],
  overlay: FirefliesCanvas,
  vars: {
    "--bg0": "#07140d", "--bg1": "#0b1a11", "--bg2": "#102216", "--bg3": "#182f1f", "--bg4": "#213d29",
    "--border": "rgba(163,230,53,0.09)", "--border2": "rgba(163,230,53,0.17)", "--border3": "rgba(163,230,53,0.3)",
    "--t0": "#e8f3e0", "--t1": "#9bb392", "--t2": "#57704f",
    "--accent": "#a3e635", "--accent2": "#bef264", "--accent3": "rgba(163,230,53,0.12)",
    "--cyan": "#2dd4bf", "--green": "#4ade80", "--red": "#f87171", "--yellow": "#facc15", "--purple": "#c084fc", "--pink": "#f472b6",
    "--sans": "'Plus Jakarta Sans',sans-serif", "--mono": "'JetBrains Mono',monospace",
    "--r": "10px", "--rl": "14px",
  },
};
