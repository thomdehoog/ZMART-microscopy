/**
 * A small burst of confetti, inside one box.
 *
 * For the end of a protocol run: something joyful, small and with taste
 * (Thom, 2026-09-28) -- a few dozen pieces in the page's own colours, thrown
 * up from the bottom of the box, tumbling down and gone after three
 * seconds. Never outside the canvas it is drawn on, never on a loop, and
 * nothing at all for an operator who asked their system for reduced motion.
 * Returns a function that stops it early.
 */

const PIECES = 56;
const LIFE_MS = 3000;

export function burst(canvas, colours) {
  if (typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches) {
    return () => {};
  }
  const dpr = window.devicePixelRatio || 1;
  const w = canvas.clientWidth, h = canvas.clientHeight;
  canvas.width = Math.round(w * dpr);
  canvas.height = Math.round(h * dpr);
  const ctx = canvas.getContext("2d");
  ctx.scale(dpr, dpr);
  const pieces = Array.from({ length: PIECES }, (_, i) => ({
    x: w * (0.25 + 0.5 * Math.random()),
    y: h + 4,
    vx: (Math.random() - 0.5) * 160,
    vy: -(120 + Math.random() * 90),
    spin: (Math.random() - 0.5) * 12,
    angle: Math.random() * Math.PI,
    size: 4 + Math.random() * 4,
    colour: colours[i % colours.length],
  }));
  let started = null;
  let frame = null;
  const draw = (now) => {
    if (started === null) started = now;
    const t = (now - started) / 1000;
    const gone = now - started > LIFE_MS;
    ctx.clearRect(0, 0, w, h);
    if (gone) return;
    const fade = Math.max(0, 1 - Math.max(0, now - started - LIFE_MS * 0.6) / (LIFE_MS * 0.4));
    ctx.globalAlpha = fade;
    for (const p of pieces) {
      const x = p.x + p.vx * t;
      const y = p.y + p.vy * t + 70 * t * t;
      if (y > h + 8) continue;
      ctx.save();
      ctx.translate(x, y);
      ctx.rotate(p.angle + p.spin * t);
      ctx.fillStyle = p.colour;
      ctx.fillRect(-p.size / 2, -p.size / 4, p.size, p.size / 2);
      ctx.restore();
    }
    ctx.globalAlpha = 1;
    frame = requestAnimationFrame(draw);
  };
  frame = requestAnimationFrame(draw);
  return () => { if (frame) cancelAnimationFrame(frame); ctx.clearRect(0, 0, w, h); };
}
