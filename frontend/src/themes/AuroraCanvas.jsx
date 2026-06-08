import { useEffect, useRef } from "react";

export default function AuroraCanvas({ count = 3 }) {
  const ref = useRef(null);
  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    const reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const COLORS = ["#2dd4bf", "#4ade80", "#a78bfa"];
    let raf, W = 0, H = 0, dpr = 1;

    const resize = () => {
      dpr = Math.min(window.devicePixelRatio || 1, 2);
      W = canvas.offsetWidth; H = canvas.offsetHeight;
      canvas.width = Math.round(W * dpr);
      canvas.height = Math.round(H * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };
    resize();
    window.addEventListener("resize", resize);

    const ribbons = Array.from({ length: count }, (_, i) => ({
      y: H * (0.12 + i * 0.1),
      amp: 18 + Math.random() * 30,
      len: 220 + Math.random() * 260,
      phase: Math.random() * Math.PI * 2,
      speed: 0.004 + Math.random() * 0.005,
      bob: Math.random() * Math.PI * 2,
      bobSpeed: 0.003 + Math.random() * 0.004,
      thick: 55 + Math.random() * 55,
      color: COLORS[i % COLORS.length],
    }));

    const drawRibbon = (r) => {
      const yc = r.y + Math.sin(r.bob) * 24;
      const grad = ctx.createLinearGradient(0, yc - r.thick, 0, yc + r.thick);
      grad.addColorStop(0, "rgba(0,0,0,0)");
      grad.addColorStop(0.5, r.color);
      grad.addColorStop(1, "rgba(0,0,0,0)");
      ctx.fillStyle = grad;
      ctx.globalAlpha = 0.13;
      ctx.beginPath();
      ctx.moveTo(0, yc - r.thick);
      for (let x = 0; x <= W; x += 14) ctx.lineTo(x, yc + Math.sin(x / r.len + r.phase) * r.amp - r.thick);
      for (let x = W; x >= 0; x -= 14) ctx.lineTo(x, yc + Math.sin(x / r.len + r.phase) * r.amp + r.thick);
      ctx.closePath();
      ctx.fill();
    };

    const render = () => {
      ctx.clearRect(0, 0, W, H);
      ctx.globalCompositeOperation = "lighter";
      ribbons.forEach(drawRibbon);
      ctx.globalAlpha = 1;
      ctx.globalCompositeOperation = "source-over";
    };

    if (reduce) { render(); return () => window.removeEventListener("resize", resize); }

    const tick = () => {
      for (const r of ribbons) { r.phase += r.speed; r.bob += r.bobSpeed; }
      render();
      raf = requestAnimationFrame(tick);
    };
    tick();

    return () => { cancelAnimationFrame(raf); window.removeEventListener("resize", resize); };
  }, [count]);

  return <canvas ref={ref} style={{ position: "fixed", inset: 0, width: "100%", height: "100%", pointerEvents: "none", zIndex: 0 }} />;
}
