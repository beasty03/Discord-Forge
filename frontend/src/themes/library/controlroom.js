// themes/library/controlroom.js
import ScanLineOverlay from "../ScanLineOverlay.jsx";

export default {
  id: "controlroom",
  overlay: ScanLineOverlay,
  name: "Control Room",
  desc: "Phosphor green terminal",
  order: 1,
  preview: ["#030506", "#070d0a", "#00ff41"],
  vars: {
    "--bg0": "#030506", "--bg1": "#070d0a", "--bg2": "#0a1410", "--bg3": "#0e1c17", "--bg4": "#132318",
    "--border": "rgba(0,255,65,0.08)", "--border2": "rgba(0,255,65,0.18)", "--border3": "rgba(0,255,65,0.32)",
    "--t0": "#e0ffe8", "--t1": "#7ab890", "--t2": "#3a6048",
    "--accent": "#00ff41", "--accent2": "#00c832", "--accent3": "rgba(0,255,65,0.1)",
    "--cyan": "#00d4ff", "--green": "#00ff41", "--red": "#ff4444", "--yellow": "#ffb700", "--purple": "#00d4ff", "--pink": "#ff44aa",
    "--sans": "'JetBrains Mono',monospace", "--mono": "'JetBrains Mono',monospace",
    "--r": "4px", "--rl": "6px",
  },
};
