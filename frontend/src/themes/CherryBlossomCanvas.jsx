import { useEffect, useRef } from "react";

export default function CherryBlossomCanvas() {
  const canvasRef = useRef(null);
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    let raf;
    const resize = () => { canvas.width = canvas.offsetWidth; canvas.height = canvas.offsetHeight; };
    resize();
    window.addEventListener('resize', resize);
    const COLORS = ['#fce7f3','#fbcfe8','#f9a8d4','#f472b6','#ec4899','#fdf2f8','#ffe4ee'];
    const petals = Array.from({length:34}, () => ({
      x: Math.random() * window.innerWidth,
      y: Math.random() * -600 - 20,
      size: 4 + Math.random() * 9,
      rot: Math.random() * Math.PI * 2,
      rotSpeed: (Math.random() - 0.5) * 0.04,
      speedX: (Math.random() - 0.5) * 0.7,
      speedY: 0.6 + Math.random() * 1.3,
      color: COLORS[Math.floor(Math.random() * COLORS.length)],
      opacity: 0.35 + Math.random() * 0.5,
      wobble: Math.random() * Math.PI * 2,
      wobbleSpeed: 0.01 + Math.random() * 0.02,
    }));
    const draw = (p) => {
      ctx.save();
      ctx.translate(p.x, p.y);
      ctx.rotate(p.rot);
      ctx.globalAlpha = p.opacity;
      ctx.beginPath();
      ctx.moveTo(0, 0);
      ctx.bezierCurveTo(p.size, -p.size * 0.5, p.size * 1.4, p.size * 0.8, 0, p.size * 1.2);
      ctx.bezierCurveTo(-p.size * 1.4, p.size * 0.8, -p.size, -p.size * 0.5, 0, 0);
      ctx.fillStyle = p.color;
      ctx.fill();
      ctx.restore();
    };
    const tick = () => {
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      petals.forEach(p => {
        p.wobble += p.wobbleSpeed;
        p.x += p.speedX + Math.sin(p.wobble) * 0.4;
        p.y += p.speedY;
        p.rot += p.rotSpeed;
        if (p.y > canvas.height + 30) { p.y = -20; p.x = Math.random() * canvas.width; }
        draw(p);
      });
      raf = requestAnimationFrame(tick);
    };
    tick();
    return () => { cancelAnimationFrame(raf); window.removeEventListener('resize', resize); };
  }, []);
  return <canvas ref={canvasRef} style={{position:'fixed',inset:0,width:'100%',height:'100%',pointerEvents:'none',zIndex:0}}/>;
}
