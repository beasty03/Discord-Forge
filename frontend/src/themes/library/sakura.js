// themes/library/sakura.js
import CherryBlossomCanvas from "../CherryBlossomCanvas.jsx";

export default {
  id: "sakura",
  name: "Sakura",
  desc: "Cherry blossom · soft pink",
  order: 3,
  preview: ["#fdf6f9", "#fce7f3", "#ec4899"],
  overlay: CherryBlossomCanvas,
  vars: {
    "--bg0": "#fdf6f9", "--bg1": "#ffffff", "--bg2": "#fef0f6", "--bg3": "#fce7f3", "--bg4": "#fbcfe8",
    "--border": "rgba(236,72,153,.12)", "--border2": "rgba(236,72,153,.24)", "--border3": "rgba(236,72,153,.38)",
    "--t0": "#3d1f2e", "--t1": "#7a4d65", "--t2": "#b08098",
    "--accent": "#ec4899", "--accent2": "#f472b6", "--accent3": "rgba(236,72,153,.1)",
    "--cyan": "#c084fc", "--green": "#4ade80", "--red": "#f43f5e", "--yellow": "#f59e0b", "--purple": "#c084fc", "--pink": "#f9a8d4",
    "--sans": "'DM Sans',sans-serif", "--mono": "'JetBrains Mono',monospace",
    "--r": "12px", "--rl": "18px",
  },
};
