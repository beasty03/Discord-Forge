import { useEffect, useRef } from "react";

export default function FirefliesCanvas({ count = 42 }) {
  const ref = useRef(null);
  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    const reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const COLORS = ["#a3e635", "#bef264", "#d9f99d", "#facc15"];
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

    const fly = () => ({
      x: Math.random() * W,
      y: Math.random() * H,
      size: 1 + Math.random() * 1.8,
      px: Math.random() * Math.PI * 2,
      py: Math.random() * Math.PI * 2,
      pxs: 0.004 + Math.random() * 0.006,
      pys: 0.004 + Math.random() * 0.006,
      drift: 0.15 + Math.random() * 0.25,
      pulse: Math.random() * Math.PI * 2,
      pulseSpeed: 0.01 + Math.random() * 0.03,
      base: 0.3 + Math.random() * 0.5,
      color: COLORS[(Math.random() * COLORS.length) | 0],
    });

    const flies = Array.from({ length: count }, fly);

    const draw = (f, a) => {
      ctx.globalAlpha = a;
      ctx.fillStyle = f.color;
      ctx.beginPath();
      ctx.arc(f.x, f.y, f.size, 0, Math.PI * 2);
      ctx.fill();
    };

    if (reduce) {
      ctx.globalCompositeOperation = "lighter";
      flies.forEach((f) => draw(f, f.base * 0.6));
      ctx.globalAlpha = 1;
      return () => window.removeEventListener("resize", resize);
    }

    const tick = () => {
      ctx.clearRect(0, 0, W, H);
      ctx.globalCompositeOperation = "lighter";
      for (const f of flies) {
        f.px += f.pxs; f.py += f.pys; f.pulse += f.pulseSpeed;
        f.x += Math.cos(f.px) * f.drift;
        f.y += Math.sin(f.py) * f.drift;
        if (f.x < -5) f.x = W + 5; else if (f.x > W + 5) f.x = -5;
        if (f.y < -5) f.y = H + 5; else if (f.y > H + 5) f.y = -5;
        draw(f, f.base * (0.4 + 0.6 * (0.5 + 0.5 * Math.sin(f.pulse))));
      }
      ctx.globalAlpha = 1;
      ctx.globalCompositeOperation = "source-over";
      raf = requestAnimationFrame(tick);
    };
    tick();

    return () => { cancelAnimationFrame(raf); window.removeEventListener("resize", resize); };
  }, [count]);

  return <canvas ref={ref} style={{ position: "fixed", inset: 0, width: "100%", height: "100%", pointerEvents: "none", zIndex: 0 }} />;
}
