import { useEffect, useRef } from "react";

export default function CircuitCanvas({ grid = 30, density = 0.7 }) {
  const ref = useRef(null);
  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    const reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const TRACE = "#2f6f63";
    const PULSE = ["#5cf0d8", "#22d3ee", "#3ee68a"];
    const DIRS = [[1, 0], [-1, 0], [0, 1], [0, -1], [1, 1], [-1, 1], [1, -1], [-1, -1]];
    let raf, W = 0, H = 0, dpr = 1, traces = [];

    const build = () => {
      traces = [];
      const cols = Math.floor(W / grid), rows = Math.floor(H / grid);
      const n = Math.max(8, Math.floor(cols * rows * 0.04 * density));
      for (let i = 0; i < n; i++) {
        let cx = (Math.random() * cols) | 0, cy = (Math.random() * rows) | 0;
        const pts = [[cx * grid, cy * grid]];
        const segs = 4 + ((Math.random() * 6) | 0);
        let d = DIRS[(Math.random() * 4) | 0];
        for (let s = 0; s < segs; s++) {
          if (Math.random() < 0.4) d = DIRS[(Math.random() * DIRS.length) | 0];
          const step = 1 + ((Math.random() * 4) | 0);
          cx = Math.max(0, Math.min(cols, cx + d[0] * step));
          cy = Math.max(0, Math.min(rows, cy + d[1] * step));
          pts.push([cx * grid, cy * grid]);
        }
        let total = 0; const cum = [0];
        for (let k = 1; k < pts.length; k++) {
          total += Math.hypot(pts[k][0] - pts[k - 1][0], pts[k][1] - pts[k - 1][1]);
          cum.push(total);
        }
        traces.push({
          pts, cum, total,
          pulse: total > 0 && Math.random() < 0.55,
          p: Math.random(),
          speed: 0.0015 + Math.random() * 0.0035,
          color: PULSE[(Math.random() * PULSE.length) | 0],
        });
      }
    };

    const resize = () => {
      dpr = Math.min(window.devicePixelRatio || 1, 2);
      W = canvas.offsetWidth; H = canvas.offsetHeight;
      canvas.width = Math.round(W * dpr);
      canvas.height = Math.round(H * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      build();
    };
    resize();
    window.addEventListener("resize", resize);

    const at = (tr, dist) => {
      const { pts, cum } = tr;
      for (let k = 1; k < pts.length; k++) {
        if (dist <= cum[k]) {
          const seg = cum[k] - cum[k - 1] || 1;
          const u = (dist - cum[k - 1]) / seg;
          return [pts[k - 1][0] + (pts[k][0] - pts[k - 1][0]) * u, pts[k - 1][1] + (pts[k][1] - pts[k - 1][1]) * u];
        }
      }
      return pts[pts.length - 1];
    };

    const drawTraces = () => {
      ctx.globalCompositeOperation = "source-over";
      ctx.strokeStyle = TRACE;
      ctx.lineWidth = 1.4;
      ctx.lineJoin = "round";
      ctx.lineCap = "round";
      ctx.globalAlpha = 0.22;
      for (const tr of traces) {
        ctx.beginPath();
        ctx.moveTo(tr.pts[0][0], tr.pts[0][1]);
        for (let k = 1; k < tr.pts.length; k++) ctx.lineTo(tr.pts[k][0], tr.pts[k][1]);
        ctx.stroke();
      }
      ctx.fillStyle = TRACE;
      ctx.globalAlpha = 0.4;
      for (const tr of traces) {
        for (const v of [tr.pts[0], tr.pts[tr.pts.length - 1]]) {
          ctx.beginPath(); ctx.arc(v[0], v[1], 2.4, 0, Math.PI * 2); ctx.fill();
        }
      }
    };

    const drawPulses = () => {
      ctx.globalCompositeOperation = "lighter";
      for (const tr of traces) {
        if (!tr.pulse) continue;
        const head = tr.p * tr.total;
        for (let j = 0; j < 7; j++) {
          const d = head - j * 6;
          if (d < 0) break;
          const [x, y] = at(tr, d);
          ctx.globalAlpha = (1 - j / 7) * 0.6;
          ctx.fillStyle = tr.color;
          ctx.beginPath(); ctx.arc(x, y, j === 0 ? 2.4 : 1.6, 0, Math.PI * 2); ctx.fill();
        }
      }
      ctx.globalCompositeOperation = "source-over";
      ctx.globalAlpha = 1;
    };

    const render = () => {
      ctx.clearRect(0, 0, W, H);
      drawTraces();
      drawPulses();
      ctx.globalAlpha = 1;
    };

    if (reduce) { render(); return () => window.removeEventListener("resize", resize); }

    const tick = () => {
      for (const tr of traces) { if (tr.pulse) { tr.p += tr.speed; if (tr.p > 1) tr.p = 0; } }
      render();
      raf = requestAnimationFrame(tick);
    };
    tick();

    return () => { cancelAnimationFrame(raf); window.removeEventListener("resize", resize); };
  }, [grid, density]);

  return <canvas ref={ref} style={{ position: "fixed", inset: 0, width: "100%", height: "100%", pointerEvents: "none", zIndex: 0 }} />;
}
