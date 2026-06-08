import { useEffect, useRef } from "react";

const SWELLS = [
  { color: "#a9cce0", base: 0.86, amp: 10, len: 240, speed: 0.018, alpha: 0.5 },
  { color: "#4d82ab", base: 0.92, amp: 13, len: 200, speed: 0.026, alpha: 0.6 },
  { color: "#1d4e79", base: 0.97, amp: 15, len: 170, speed: 0.034, alpha: 0.8 },
];

// Top-edge of the curl, in local box fractions (0..1). Three cubic-bezier segments:
// back ridge rising to the peak, crest sweeping right, then the lip hooking down.
const E1 = [[0, 0.50], [0.18, 0.18], [0.30, 0.05], [0.46, 0.04]];
const E2 = [[0.46, 0.04], [0.66, 0.03], [0.86, 0.10], [0.92, 0.26]];
const E3 = [[0.92, 0.26], [0.95, 0.42], [0.80, 0.47], [0.66, 0.42]];

const lbez = (seg, u) => {
  const v = 1 - u, a = v * v * v, b = 3 * v * v * u, c = 3 * v * u * u, d = u * u * u;
  return [
    a * seg[0][0] + b * seg[1][0] + c * seg[2][0] + d * seg[3][0],
    a * seg[0][1] + b * seg[1][1] + c * seg[2][1] + d * seg[3][1],
  ];
};

export default function GreatWaveCanvas() {
  const ref = useRef(null);
  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    const reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    let raf, W = 0, H = 0, dpr = 1, t = 0;
    const swellPh = SWELLS.map(() => Math.random() * 1000);

    // Foam + spray precomputed once in local coords so it shimmers instead of flickering.
    const sampleFoam = (seg, n, rBase) => Array.from({ length: n + 1 }, (_, i) => {
      const p = lbez(seg, i / n);
      return { lx: p[0] + (Math.random() - 0.5) * 0.025, ly: p[1] + (Math.random() - 0.5) * 0.025,
        r: rBase * (0.5 + Math.random()), ph: Math.random() * 6.28, base: 0.4 + Math.random() * 0.45 };
    });
    const foam = [...sampleFoam(E1, 16, 0.012), ...sampleFoam(E2, 18, 0.016), ...sampleFoam(E3, 16, 0.022)];
    const claws = [];
    const addClaw = (sx, sy, dx, dy, n) => {
      for (let i = 0; i < n; i++) {
        const k = i / n;
        claws.push({ lx: sx + dx * k + (Math.random() - 0.5) * 0.012, ly: sy + dy * k,
          r: 0.02 * (1 - k * 0.7), base: (1 - k) * 0.7, ph: Math.random() * 6.28 });
      }
    };
    addClaw(0.92, 0.26, 0.10, -0.07, 6);
    addClaw(0.92, 0.26, 0.14, 0.02, 7);
    addClaw(0.92, 0.26, 0.09, 0.09, 5);
    addClaw(0.80, 0.09, 0.05, -0.10, 5);

    const resize = () => {
      dpr = Math.min(window.devicePixelRatio || 1, 2);
      W = canvas.offsetWidth; H = canvas.offsetHeight;
      canvas.width = Math.round(W * dpr);
      canvas.height = Math.round(H * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };
    resize();
    window.addEventListener("resize", resize);

    const drawSwell = (L, ph) => {
      const baseY = H * L.base;
      ctx.globalAlpha = L.alpha;
      ctx.fillStyle = L.color;
      ctx.beginPath();
      ctx.moveTo(0, H);
      for (let x = 0; x <= W; x += 8) ctx.lineTo(x, baseY + Math.sin(x / L.len + ph) * L.amp);
      ctx.lineTo(W, H);
      ctx.closePath();
      ctx.fill();
    };

    const drawWave = () => {
      const s = Math.min(H * 0.94, W * 0.72);
      const ox = -0.05 * W;
      const oy = H - s + Math.sin(t) * (s * 0.012);
      const P = (lx, ly) => [ox + lx * s, oy + ly * s];
      const seg = (e) => ctx.bezierCurveTo(...P(e[1][0], e[1][1]), ...P(e[2][0], e[2][1]), ...P(e[3][0], e[3][1]));

      ctx.globalAlpha = 0.62;
      ctx.fillStyle = "#1d4e79";
      ctx.beginPath();
      ctx.moveTo(...P(E1[0][0], E1[0][1]));
      seg(E1); seg(E2); seg(E3);
      ctx.bezierCurveTo(...P(0.62, 0.66), ...P(0.74, 0.85), ...P(0.80, 1.0));
      ctx.lineTo(ox, H);
      ctx.closePath();
      ctx.fill();

      ctx.globalAlpha = 0.5;
      ctx.fillStyle = "#4d82ab";
      ctx.beginPath();
      ctx.moveTo(...P(0.30, 0.16));
      ctx.bezierCurveTo(...P(0.5, 0.12), ...P(0.72, 0.2), ...P(0.70, 0.36));
      ctx.bezierCurveTo(...P(0.5, 0.34), ...P(0.34, 0.34), ...P(0.30, 0.16));
      ctx.closePath();
      ctx.fill();

      ctx.globalAlpha = 0.55;
      ctx.fillStyle = "#a9cce0";
      ctx.beginPath();
      ctx.moveTo(...P(0.66, 0.42));
      ctx.bezierCurveTo(...P(0.84, 0.30), ...P(0.88, 0.36), ...P(0.72, 0.46));
      ctx.bezierCurveTo(...P(0.70, 0.45), ...P(0.66, 0.42), ...P(0.66, 0.42));
      ctx.closePath();
      ctx.fill();

      ctx.fillStyle = "#f6f1e6";
      for (const f of foam) {
        const [px, py] = P(f.lx, f.ly);
        ctx.globalAlpha = f.base * (0.55 + 0.45 * Math.sin(f.ph + t * 2));
        ctx.beginPath();
        ctx.arc(px, py, f.r * s, 0, Math.PI * 2);
        ctx.fill();
      }
      for (const c of claws) {
        const [px, py] = P(c.lx, c.ly);
        ctx.globalAlpha = c.base * (0.6 + 0.4 * Math.sin(c.ph + t * 2));
        ctx.beginPath();
        ctx.arc(px, py, c.r * s, 0, Math.PI * 2);
        ctx.fill();
      }
      ctx.globalAlpha = 1;
    };

    const render = () => {
      ctx.clearRect(0, 0, W, H);
      SWELLS.forEach((L, i) => drawSwell(L, swellPh[i]));
      drawWave();
      ctx.globalAlpha = 1;
    };

    if (reduce) { render(); return () => window.removeEventListener("resize", resize); }

    const tick = () => {
      t += 0.02;
      for (let i = 0; i < SWELLS.length; i++) swellPh[i] += SWELLS[i].speed;
      render();
      raf = requestAnimationFrame(tick);
    };
    tick();

    return () => { cancelAnimationFrame(raf); window.removeEventListener("resize", resize); };
  }, []);

  return <canvas ref={ref} style={{ position: "fixed", inset: 0, width: "100%", height: "100%", pointerEvents: "none", zIndex: 0 }} />;
}
