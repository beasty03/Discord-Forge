// themes/library/mainframe.js
import ScanlinesCanvas from "../ScanlinesCanvas.jsx";

export default {
  id: "mainframe",
  name: "Mainframe",
  desc: "Amber CRT · scanlines",
  order: 15,
  preview: ["#0a0700", "#100b02", "#ffb000"],
  // ScanlinesCanvas defaults to amber (#ffb000), matching the accent.
  overlay: ScanlinesCanvas,
  vars: {
    "--bg0": "#0a0700", "--bg1": "#100b02", "--bg2": "#160f04", "--bg3": "#1e1607", "--bg4": "#281d0a",
    "--border": "rgba(255,176,0,0.1)", "--border2": "rgba(255,176,0,0.18)", "--border3": "rgba(255,176,0,0.3)",
    "--t0": "#ffe8c2", "--t1": "#c79a54", "--t2": "#6e552a",
    "--accent": "#ffb000", "--accent2": "#ffc740", "--accent3": "rgba(255,176,0,0.12)",
    "--cyan": "#4cc9d6", "--green": "#8fcf5a", "--red": "#ff5a3c", "--yellow": "#ffca3a", "--purple": "#c69bff", "--pink": "#ff7aa0",
    "--sans": "'JetBrains Mono',monospace", "--mono": "'JetBrains Mono',monospace",
    "--r": "4px", "--rl": "6px",
  },
};
