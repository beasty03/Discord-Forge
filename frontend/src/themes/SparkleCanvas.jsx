import { useEffect, useRef } from "react";

export default function SparkleCanvas({ count = 30 }) {
  const ref = useRef(null);
  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    const reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const COLORS = ["#ffffff", "#ffe9a8", "#ff9ed1", "#aef0ff"];
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

    const make = () => ({
      x: Math.random() * W,
      y: Math.random() * H,
      max: 5 + Math.random() * 11,
      phase: Math.random(),
      speed: 0.004 + Math.random() * 0.008,
      rot: Math.random() * Math.PI,
      rotSpeed: (Math.random() - 0.5) * 0.02,
      drift: 0.1 + Math.random() * 0.2,
      color: COLORS[(Math.random() * COLORS.length) | 0],
    });

    const stars = Array.from({ length: count }, make);

    const sparkle = (s, scale, alpha) => {
      const o = s.max * scale, inr = o * 0.16;
      ctx.save();
      ctx.translate(s.x, s.y);
      ctx.rotate(s.rot);
      ctx.globalAlpha = alpha;
      ctx.fillStyle = s.color;
      ctx.beginPath();
      for (let i = 0; i < 8; i++) {
        const ang = (i * Math.PI) / 4 - Math.PI / 2;
        const r = i % 2 === 0 ? o : inr;
        const px = Math.cos(ang) * r, py = Math.sin(ang) * r;
        i === 0 ? ctx.moveTo(px, py) : ctx.lineTo(px, py);
      }
      ctx.closePath();
      ctx.fill();
      ctx.beginPath();
      ctx.arc(0, 0, Math.max(0.6, o * 0.12), 0, Math.PI * 2);
      ctx.fill();
      ctx.restore();
    };

    const render = (animate) => {
      ctx.clearRect(0, 0, W, H);
      ctx.globalCompositeOperation = "lighter";
      for (const s of stars) {
        const e = Math.sin(s.phase * Math.PI);
        sparkle(s, 0.35 + 0.65 * e, animate ? e * 0.9 : 0.5 + 0.4 * e);
      }
      ctx.globalAlpha = 1;
      ctx.globalCompositeOperation = "source-over";
    };

    if (reduce) { render(false); return () => window.removeEventListener("resize", resize); }

    const tick = () => {
      for (const s of stars) {
        s.phase += s.speed;
        s.rot += s.rotSpeed;
        s.y -= s.drift;
        if (s.phase >= 1) Object.assign(s, make(), { y: Math.random() * H });
        if (s.y < -12) s.y = H + 12;
      }
      render(true);
      raf = requestAnimationFrame(tick);
    };
    tick();

    return () => { cancelAnimationFrame(raf); window.removeEventListener("resize", resize); };
  }, [count]);

  return <canvas ref={ref} style={{ position: "fixed", inset: 0, width: "100%", height: "100%", pointerEvents: "none", zIndex: 0 }} />;
}
