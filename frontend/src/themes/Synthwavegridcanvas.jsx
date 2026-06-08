import { useEffect, useRef } from "react";

export default function SynthwaveGridCanvas({
  horizon = 0.58,
  color = "#ff3d9a",
  glow = "#22d3ee",
  lines = 18,
  speed = 0.0045,
}) {
  const ref = useRef(null);
  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    const reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    let raf, W = 0, H = 0, dpr = 1, phase = 0;

    const resize = () => {
      dpr = Math.min(window.devicePixelRatio || 1, 2);
      W = canvas.offsetWidth; H = canvas.offsetHeight;
      canvas.width = Math.round(W * dpr);
      canvas.height = Math.round(H * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };
    resize();
    window.addEventListener("resize", resize);

    const render = () => {
      const hy = H * horizon;
      const ground = H - hy;
      const cx = W / 2;
      ctx.clearRect(0, 0, W, H);
      ctx.globalCompositeOperation = "lighter";
      ctx.lineWidth = 1;

      ctx.globalAlpha = 0.5;
      ctx.strokeStyle = glow;
      ctx.beginPath();
      ctx.moveTo(0, hy);
      ctx.lineTo(W, hy);
      ctx.stroke();

      ctx.strokeStyle = color;
      const spacing = W / 7;
      for (let i = -10; i <= 10; i++) {
        ctx.globalAlpha = 0.16;
        ctx.beginPath();
        ctx.moveTo(cx, hy);
        ctx.lineTo(cx + i * spacing, H);
        ctx.stroke();
      }
      for (let k = 0; k < lines; k++) {
        const f = ((k / lines) + phase) % 1;
        const y = hy + ground * f * f;
        ctx.globalAlpha = 0.05 + f * 0.3;
        ctx.beginPath();
        ctx.moveTo(0, y);
        ctx.lineTo(W, y);
        ctx.stroke();
      }
      ctx.globalAlpha = 1;
      ctx.globalCompositeOperation = "source-over";
    };

    if (reduce) {
      render();
      return () => window.removeEventListener("resize", resize);
    }

    const tick = () => {
      phase = (phase + speed) % 1;
      render();
      raf = requestAnimationFrame(tick);
    };
    tick();

    return () => { cancelAnimationFrame(raf); window.removeEventListener("resize", resize); };
  }, [horizon, color, glow, lines, speed]);

  return <canvas ref={ref} style={{ position: "fixed", inset: 0, width: "100%", height: "100%", pointerEvents: "none", zIndex: 0 }} />;
}