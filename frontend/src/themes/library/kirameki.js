// themes/library/kirameki.js
import SparkleCanvas from "../SparkleCanvas.jsx";

export default {
  id: "kirameki",
  name: "Kirameki",
  desc: "Anime twilight · sparkles",
  order: 17,
  preview: ["#0b0a1f", "#131134", "#5ad1ff"],
  overlay: SparkleCanvas,
  vars: {
    "--bg0": "#0b0a1f", "--bg1": "#131134", "--bg2": "#1a1746", "--bg3": "#242059", "--bg4": "#312a73",
    "--border": "rgba(190,150,255,0.12)", "--border2": "rgba(190,150,255,0.22)", "--border3": "rgba(190,150,255,0.36)",
    "--t0": "#f3ecff", "--t1": "#b9a8e6", "--t2": "#6f6299",
    "--accent": "#5ad1ff", "--accent2": "#93e3ff", "--accent3": "rgba(90,209,255,0.14)",
    "--cyan": "#5ad1ff", "--green": "#5ef0c0", "--red": "#ff6b8b", "--yellow": "#ffd45e", "--purple": "#c08bff", "--pink": "#ff7ec4",
    "--sans": "'Plus Jakarta Sans',sans-serif", "--mono": "'JetBrains Mono',monospace",
    "--r": "14px", "--rl": "20px",
  },
};
