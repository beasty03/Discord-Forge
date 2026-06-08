// themes/library/circuit.js
import CircuitCanvas from "../CircuitCanvas.jsx";

export default {
  id: "circuit",
  name: "Circuit",
  desc: "PCB traces · live current",
  order: 19,
  preview: ["#04110f", "#07201d", "#2ee6c6"],
  overlay: CircuitCanvas,
  vars: {
    "--bg0": "#04110f", "--bg1": "#07201d", "--bg2": "#0a2a26", "--bg3": "#0f3833", "--bg4": "#164842",
    "--border": "rgba(46,230,198,0.1)", "--border2": "rgba(46,230,198,0.18)", "--border3": "rgba(46,230,198,0.3)",
    "--t0": "#d6f5ee", "--t1": "#84b3a9", "--t2": "#466860",
    "--accent": "#2ee6c6", "--accent2": "#5cf0d8", "--accent3": "rgba(46,230,198,0.13)",
    "--cyan": "#22d3ee", "--green": "#3ee68a", "--red": "#ff5a5a", "--yellow": "#ffd23f", "--purple": "#b794ff", "--pink": "#ff6fb5",
    "--sans": "'JetBrains Mono',monospace", "--mono": "'JetBrains Mono',monospace",
    "--r": "4px", "--rl": "6px",
  },
};
