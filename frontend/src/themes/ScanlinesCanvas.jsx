import { useEffect, useRef } from "react";

export default function ScanlinesCanvas({ color = "#ffb000", spacing = 3, base = 0.05 }) {
  const ref = useRef(null);
  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    const reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    let raf, W = 0, H = 0, dpr = 1, offset = 0, roll = 0, t = 0;

    const resize = () => {
      dpr = Math.min(window.devicePixelRatio || 1, 2);
      W = canvas.offsetWidth; H = canvas.offsetHeight;
      canvas.width = Math.round(W * dpr);
      canvas.height = Math.round(H * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };
    resize();
    window.addEventListener("resize", resize);

    const paint = (flicker) => {
      ctx.clearRect(0, 0, W, H);
      ctx.fillStyle = color;
      ctx.globalAlpha = base * flicker;
      for (let y = offset; y < H; y += spacing) ctx.fillRect(0, y, W, 1);
      ctx.globalAlpha = base * 2.4 * flicker;
      ctx.fillRect(0, roll, W, 46);
      ctx.globalAlpha = 1;
    };

    if (reduce) { paint(1); return () => window.removeEventListener("resize", resize); }

    const tick = () => {
      t += 1;
      offset = (offset + 0.25) % spacing;
      roll = (roll + 0.6) % (H + 60) - 46;
      const flicker = 0.85 + 0.15 * Math.sin(t * 0.4) * Math.random();
      paint(Math.max(0.4, flicker));
      raf = requestAnimationFrame(tick);
    };
    tick();

    return () => { cancelAnimationFrame(raf); window.removeEventListener("resize", resize); };
  }, [color, spacing, base]);

  return <canvas ref={ref} style={{ position: "fixed", inset: 0, width: "100%", height: "100%", pointerEvents: "none", zIndex: 0 }} />;
}
