/**
 * Fixture mode only: the pictures a Ko‘z box would send, drawn on a canvas. Flat, stylised
 * scenes of a pharmacy (shelves of medicine boxes, the counter with its green cross, the door,
 * the sales floor, the storeroom) with figures in coats, never photos and never faces: the
 * customers are seen from behind, the pharmacists in white coats have no features. Masks are
 * blacked out as the agent does. Live frames and snapshots are unannotated; alert photos get the
 * zones, the boxes and the waiting times drawn in, like the agent's annotated JPEG.
 */
import type { Point, Zone } from "../types";
import { boxOf, rng, type Body, type SceneKind } from "./sim";

export const W = 960;
export const H = 540;

type Ctx = CanvasRenderingContext2D;

function canvas(w = W, h = H): { el: HTMLCanvasElement; ctx: Ctx } {
  const el = document.createElement("canvas");
  el.width = w;
  el.height = h;
  return { el, ctx: el.getContext("2d")! };
}

function roundRect(ctx: Ctx, x: number, y: number, w: number, h: number, r: number): void {
  const radius = Math.max(0, Math.min(r, w / 2, h / 2));
  ctx.beginPath();
  ctx.moveTo(x + radius, y);
  ctx.arcTo(x + w, y, x + w, y + h, radius);
  ctx.arcTo(x + w, y + h, x, y + h, radius);
  ctx.arcTo(x, y + h, x, y, radius);
  ctx.arcTo(x, y, x + w, y, radius);
  ctx.closePath();
}

function polygon(ctx: Ctx, points: readonly Point[]): void {
  ctx.beginPath();
  points.forEach(([x, y], i) => (i ? ctx.lineTo(x * W, y * H) : ctx.moveTo(x * W, y * H)));
  ctx.closePath();
}

const BOX_COLORS = ["#2a9d8f", "#3a6ea5", "#c8553d", "#6a994e", "#e09f3e", "#7b6d8d", "#d16d8a", "#4f8fb8"];

/** A shelf of medicine boxes and bottles between x0 and x1, standing on `y` (pixels). */
function shelf(ctx: Ctx, random: () => number, x0: number, x1: number, y: number, depth: number, scale = 1): void {
  let x = x0 + 4;
  while (x < x1 - 10) {
    const kind = random();
    const w = (12 + random() * 20) * scale;
    const h = (18 + random() * 22) * scale;
    if (x + w > x1 - 4) break;
    if (kind < 0.18) {
      // A bottle: amber or white, with a cap.
      const bw = w * 0.55;
      ctx.fillStyle = random() < 0.5 ? "#b5651d" : "#f4f1ea";
      roundRect(ctx, x, y - h * 0.85, bw, h * 0.85, 3 * scale);
      ctx.fill();
      ctx.fillStyle = "#e9e4da";
      ctx.fillRect(x + bw * 0.2, y - h, bw * 0.6, h * 0.16);
      x += bw + 3 * scale;
      continue;
    }
    const color = BOX_COLORS[Math.floor(random() * BOX_COLORS.length)]!;
    ctx.fillStyle = "#fbfaf6";
    ctx.fillRect(x, y - h, w, h);
    ctx.fillStyle = color;
    ctx.fillRect(x, y - h + h * 0.18, w, h * (0.16 + random() * 0.16));
    if (random() < 0.5) ctx.fillRect(x + w * 0.15, y - h * 0.3, w * 0.5, 2 * scale);
    ctx.fillStyle = "rgba(0,0,0,0.08)";
    ctx.fillRect(x + w - 2 * scale, y - h, 2 * scale, h);
    x += w + (1 + random() * 3) * scale;
  }
  // The board under the row.
  ctx.fillStyle = "#f7f4ee";
  ctx.fillRect(x0, y, x1 - x0, depth);
  ctx.fillStyle = "rgba(60,45,30,0.16)";
  ctx.fillRect(x0, y + depth, x1 - x0, 3);
}

function vignette(ctx: Ctx, strength = 0.22): void {
  const g = ctx.createRadialGradient(W / 2, H / 2, H * 0.35, W / 2, H / 2, W * 0.68);
  g.addColorStop(0, "rgba(0,0,0,0)");
  g.addColorStop(1, `rgba(20,14,8,${strength})`);
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, W, H);
}

function greenCross(ctx: Ctx, cx: number, cy: number, size: number): void {
  ctx.save();
  ctx.shadowColor = "rgba(59,178,115,0.75)";
  ctx.shadowBlur = size * 0.8;
  ctx.fillStyle = "#3bb273";
  const a = size / 3;
  ctx.fillRect(cx - a / 2, cy - size / 2, a, size);
  ctx.fillRect(cx - size / 2, cy - a / 2, size, a);
  ctx.restore();
}

function floorTiles(ctx: Ctx, top: number, vanishX: number, colors: [string, string], vanishY = top - 120): void {
  const g = ctx.createLinearGradient(0, top, 0, H);
  g.addColorStop(0, colors[0]);
  g.addColorStop(1, colors[1]);
  ctx.fillStyle = g;
  ctx.fillRect(0, top, W, H - top);
  ctx.strokeStyle = "rgba(80,64,48,0.12)";
  ctx.lineWidth = 1;
  for (let i = -10; i <= 10; i++) {
    ctx.beginPath();
    ctx.moveTo(vanishX + i * 18, top);
    ctx.lineTo(vanishX + (i * 18 - vanishX + vanishX) * ((H - vanishY) / (top - vanishY)), H);
    ctx.stroke();
  }
  for (let k = 0; k < 7; k++) {
    const y = top + (H - top) * ((k + 1) / 7) ** 1.6;
    ctx.beginPath();
    ctx.moveTo(0, y);
    ctx.lineTo(W, y);
    ctx.stroke();
  }
}

// ─── Backgrounds (drawn once per scene and branch) ──────────────────────────

interface Background {
  back: HTMLCanvasElement;
  /** Drawn over the staff and under the customers (the counter, the floor), or null. */
  front: HTMLCanvasElement | null;
}

const backgrounds = new Map<string, Background>();

function counterBackground(variant: number): Background {
  const random = rng(101 + variant);
  const back = canvas();
  const b = back.ctx;
  const wall = b.createLinearGradient(0, 0, 0, H * 0.5);
  wall.addColorStop(0, variant ? "#e6e9e4" : "#efe8dc");
  wall.addColorStop(1, variant ? "#d9ddd5" : "#e2d8c8");
  b.fillStyle = wall;
  b.fillRect(0, 0, W, H);
  // Ceiling band with recessed lights and the pharmacy's sign.
  b.fillStyle = variant ? "#cfd4cc" : "#d9cfbf";
  b.fillRect(0, 0, W, H * 0.075);
  for (let i = 0; i < 6; i++) {
    const g = b.createRadialGradient(80 + i * 160, 8, 2, 80 + i * 160, 8, 70);
    g.addColorStop(0, "rgba(255,250,235,0.9)");
    g.addColorStop(1, "rgba(255,250,235,0)");
    b.fillStyle = g;
    b.fillRect(80 + i * 160 - 70, 0, 140, 80);
  }
  greenCross(b, W * 0.5 - 70, H * 0.04, 22);
  b.fillStyle = "#2f6f4f";
  b.font = "700 17px ui-sans-serif, system-ui, sans-serif";
  b.textBaseline = "middle";
  b.fillText("DORIXONA", W * 0.5 - 48, H * 0.041);
  // Shelving behind the counter.
  b.fillStyle = variant ? "#c9cfc6" : "#d6cbb8";
  b.fillRect(W * 0.05, H * 0.085, W * 0.9, H * 0.42);
  for (const y of [0.18, 0.28, 0.38, 0.48]) shelf(b, random, W * 0.06, W * 0.94, H * y, 7);
  // Side panels.
  b.fillStyle = "rgba(255,255,255,0.35)";
  b.fillRect(W * 0.05, H * 0.085, 6, H * 0.42);
  b.fillRect(W * 0.95 - 6, H * 0.085, 6, H * 0.42);

  const front = canvas();
  const f = front.ctx;
  floorTiles(f, H * 0.64, W * 0.5, variant ? ["#cdd0c9", "#b9bcb4"] : ["#d3c9b9", "#bfb3a1"]);
  // The counter: oak top, cream front with a green stripe.
  const top = f.createLinearGradient(0, H * 0.5, 0, H * 0.565);
  top.addColorStop(0, "#e5c79f");
  top.addColorStop(1, "#c99f6f");
  f.fillStyle = top;
  f.beginPath();
  f.moveTo(W * 0.02, H * 0.5);
  f.lineTo(W * 0.98, H * 0.5);
  f.lineTo(W, H * 0.565);
  f.lineTo(0, H * 0.565);
  f.closePath();
  f.fill();
  f.fillStyle = "#f3ede3";
  f.fillRect(0, H * 0.565, W, H * 0.08);
  f.fillStyle = variant ? "#3a6ea5" : "#2a9d8f";
  f.fillRect(0, H * 0.565, W, 5);
  f.fillStyle = "rgba(70,55,40,0.12)";
  for (let x = 0.2; x < 1; x += 0.2) f.fillRect(W * x, H * 0.575, 2, H * 0.065);
  f.fillStyle = "rgba(40,30,20,0.18)";
  f.fillRect(0, H * 0.645, W, 4);
  // On the counter: the till's screen (masked later), a card terminal, a basket of boxes.
  f.fillStyle = "#2c2f33";
  roundRect(f, W * 0.79, H * 0.32, W * 0.1, H * 0.15, 5);
  f.fill();
  f.fillStyle = "#3d4247";
  f.fillRect(W * 0.835, H * 0.47, W * 0.012, H * 0.035);
  f.fillStyle = "#24272b";
  roundRect(f, W * 0.7, H * 0.47, W * 0.035, H * 0.045, 4);
  f.fill();
  f.fillStyle = "#8fb7a7";
  f.fillRect(W * 0.706, H * 0.478, W * 0.023, H * 0.012);
  f.fillStyle = "#c9b48f";
  roundRect(f, W * 0.13, H * 0.46, W * 0.11, H * 0.045, 4);
  f.fill();
  const basket = rng(7 + variant);
  for (let i = 0; i < 6; i++) {
    f.fillStyle = BOX_COLORS[Math.floor(basket() * BOX_COLORS.length)]!;
    f.fillRect(W * 0.135 + i * 16, H * 0.445 - basket() * 6, 13, 16);
  }
  return { back: back.el, front: front.el };
}

function entranceBackground(variant: number): Background {
  const random = rng(303 + variant);
  const back = canvas();
  const b = back.ctx;
  const wall = b.createLinearGradient(0, 0, 0, H * 0.42);
  wall.addColorStop(0, "#ebe5da");
  wall.addColorStop(1, "#ddd3c3");
  b.fillStyle = wall;
  b.fillRect(0, 0, W, H);
  b.fillStyle = "#d4c9b7";
  b.fillRect(0, 0, W, H * 0.06);
  // The glass door: the street beyond (the top is masked: passers-by never count).
  b.fillStyle = "#4b4f54";
  b.fillRect(W * 0.375, H * 0.085, W * 0.25, H * 0.34);
  const glass = b.createLinearGradient(0, H * 0.1, 0, H * 0.42);
  glass.addColorStop(0, "#a9c7d6");
  glass.addColorStop(1, "#e2edf1");
  b.fillStyle = glass;
  b.fillRect(W * 0.385, H * 0.1, W * 0.112, H * 0.32);
  b.fillRect(W * 0.503, H * 0.1, W * 0.112, H * 0.32);
  b.strokeStyle = "rgba(255,255,255,0.6)";
  b.lineWidth = 3;
  b.beginPath();
  b.moveTo(W * 0.4, H * 0.38);
  b.lineTo(W * 0.46, H * 0.14);
  b.moveTo(W * 0.52, H * 0.4);
  b.lineTo(W * 0.58, H * 0.16);
  b.stroke();
  b.fillStyle = "#8e9399";
  b.fillRect(W * 0.488, H * 0.24, 4, H * 0.07);
  b.fillRect(W * 0.508, H * 0.24, 4, H * 0.07);
  greenCross(b, W * 0.5, H * 0.03, 16);
  // A poster and a plant on the walls.
  b.fillStyle = "#f8f5ef";
  b.fillRect(W * 0.1, H * 0.12, W * 0.13, H * 0.2);
  b.fillStyle = "#2a9d8f";
  b.beginPath();
  b.arc(W * 0.165, H * 0.2, 26, 0, Math.PI * 2);
  b.fill();
  b.fillStyle = "#e09f3e";
  b.fillRect(W * 0.12, H * 0.27, W * 0.09, 6);
  b.fillStyle = "#6a994e";
  for (let i = 0; i < 7; i++) {
    b.beginPath();
    b.ellipse(W * 0.82 + (random() - 0.5) * 50, H * 0.25 + random() * 40, 12, 30, (random() - 0.5) * 1.6, 0, Math.PI * 2);
    b.fill();
  }
  b.fillStyle = "#a0714f";
  b.fillRect(W * 0.795, H * 0.33, 52, 42);
  floorTiles(b, H * 0.42, W * 0.5, ["#d8cfc0", "#c2b6a4"], H * 0.18);
  b.fillStyle = "#5e5a52";
  b.beginPath();
  b.moveTo(W * 0.4, H * 0.425);
  b.lineTo(W * 0.6, H * 0.425);
  b.lineTo(W * 0.63, H * 0.5);
  b.lineTo(W * 0.37, H * 0.5);
  b.closePath();
  b.fill();
  return { back: back.el, front: null };
}

function floorBackground(variant: number): Background {
  const random = rng(505 + variant);
  const back = canvas();
  const b = back.ctx;
  b.fillStyle = "#e9e2d6";
  b.fillRect(0, 0, W, H);
  b.fillStyle = "#d8cebd";
  b.fillRect(0, 0, W, H * 0.08);
  for (let i = 0; i < 5; i++) {
    b.fillStyle = "rgba(255,252,240,0.85)";
    roundRect(b, 90 + i * 190, 14, 120, 8, 4);
    b.fill();
  }
  floorTiles(b, H * 0.5, W * 0.5, ["#d6ccbd", "#beb29f"], H * 0.2);
  // Two gondolas of shelves along the walls, in perspective.
  for (const side of [-1, 1]) {
    const x0 = side < 0 ? W * 0.02 : W * 0.62;
    const x1 = side < 0 ? W * 0.38 : W * 0.98;
    b.fillStyle = "#d1c5b1";
    b.fillRect(x0, H * 0.14, x1 - x0, H * 0.38);
    for (const y of [0.24, 0.34, 0.44, 0.52]) shelf(b, random, x0 + 6, x1 - 6, H * y, 6, 0.85);
  }
  // A stand of vitamins in the middle.
  b.fillStyle = "#e09f3e";
  roundRect(b, W * 0.44, H * 0.3, W * 0.12, H * 0.2, 8);
  b.fill();
  b.fillStyle = "#fff8ea";
  b.font = "700 15px ui-sans-serif, system-ui, sans-serif";
  b.textAlign = "center";
  b.fillText("VITAMIN", W * 0.5, H * 0.35);
  b.textAlign = "start";
  for (let i = 0; i < 3; i++) shelf(b, random, W * 0.445, W * 0.555, H * (0.42 + i * 0.04), 3, 0.6);
  return { back: back.el, front: null };
}

function storeroomBackground(variant: number): Background {
  const random = rng(707 + variant);
  const back = canvas();
  const b = back.ctx;
  const wall = b.createLinearGradient(0, 0, 0, H);
  wall.addColorStop(0, "#cfd2d4");
  wall.addColorStop(1, "#b9bcbe");
  b.fillStyle = wall;
  b.fillRect(0, 0, W, H);
  floorTiles(b, H * 0.7, W * 0.55, ["#a9adb0", "#93979a"], H * 0.4);
  // A door on the left, metal racks of cartons, a medicine fridge.
  b.fillStyle = "#8b8f93";
  b.fillRect(W * 0.04, H * 0.2, W * 0.1, H * 0.52);
  b.fillStyle = "#6d7175";
  b.fillRect(W * 0.12, H * 0.45, 8, 4);
  for (const x of [0.22, 0.5]) {
    b.fillStyle = "#7d8186";
    b.fillRect(W * x, H * 0.1, 6, H * 0.62);
    b.fillRect(W * (x + 0.24), H * 0.1, 6, H * 0.62);
    for (const y of [0.25, 0.43, 0.61]) {
      b.fillStyle = "#9da1a5";
      b.fillRect(W * x, H * y, W * 0.245, 6);
      let cx = W * x + 6;
      while (cx < W * (x + 0.23)) {
        const w = 30 + random() * 26;
        const h = 26 + random() * 26;
        b.fillStyle = random() < 0.5 ? "#c8a27a" : "#b8915f";
        b.fillRect(cx, H * y - h, w, h);
        b.fillStyle = "rgba(255,255,255,0.75)";
        b.fillRect(cx + 6, H * y - h + 8, w * 0.5, 8);
        cx += w + 4;
      }
    }
  }
  b.fillStyle = "#eef1f2";
  roundRect(b, W * 0.8, H * 0.14, W * 0.14, H * 0.58, 6);
  b.fill();
  b.fillStyle = "#cfe3ea";
  b.fillRect(W * 0.81, H * 0.17, W * 0.12, H * 0.42);
  for (const y of [0.28, 0.4, 0.52]) {
    b.fillStyle = "#b8cbd2";
    b.fillRect(W * 0.81, H * y, W * 0.12, 3);
  }
  return { back: back.el, front: null };
}

function emptyBackground(): Background {
  const back = canvas();
  const b = back.ctx;
  b.fillStyle = "#e4ddd1";
  b.fillRect(0, 0, W, H);
  floorTiles(b, H * 0.6, W * 0.45, ["#cfc5b5", "#b9ad9b"], H * 0.3);
  b.fillStyle = "#bcd3df";
  b.fillRect(W * 0.6, H * 0.14, W * 0.24, H * 0.3);
  b.strokeStyle = "#f6f2ea";
  b.lineWidth = 6;
  b.strokeRect(W * 0.6, H * 0.14, W * 0.24, H * 0.3);
  b.fillStyle = "#a57c58";
  b.fillRect(W * 0.18, H * 0.5, W * 0.32, H * 0.05);
  b.fillRect(W * 0.2, H * 0.55, 8, H * 0.2);
  b.fillRect(W * 0.47, H * 0.55, 8, H * 0.2);
  b.fillStyle = "#2c2f33";
  roundRect(b, W * 0.28, H * 0.38, W * 0.12, H * 0.12, 4);
  b.fill();
  return { back: back.el, front: null };
}

function background(kind: SceneKind, variant: number): Background {
  const key = `${kind}:${variant}`;
  let found = backgrounds.get(key);
  if (!found) {
    found =
      kind === "counter"
        ? counterBackground(variant)
        : kind === "entrance"
          ? entranceBackground(variant)
          : kind === "floor"
            ? floorBackground(variant)
            : kind === "storeroom"
              ? storeroomBackground(variant)
              : emptyBackground();
    backgrounds.set(key, found);
  }
  return found;
}

// ─── People ─────────────────────────────────────────────────────────────────

const COATS = ["#5b6c8f", "#8c4a3b", "#3f5e4b", "#6b5b73", "#b08a5a", "#2f4858", "#9a6b4f", "#7a8b99", "#a2574f", "#4d6d6a"];
const HAIR = ["#2b2420", "#1c1a19", "#5a4636", "#8e8a85", "#3b2b22"];
const SCARVES = ["#c77d8e", "#6d8b9e", "#d9b26f", "#8f6f9a", "#e0ddd5"];
const SKIN = ["#e8c3a0", "#d9a982", "#c68e6a", "#e3b48f"];
const TROUSERS = ["#3d3a4b", "#4a5a78", "#2f2f33", "#5b4b3f"];

function pick<T>(list: readonly T[], seed: number, salt: number): T {
  return list[Math.abs(Math.floor(seed * 7.31 + salt * 13.7)) % list.length]!;
}

function drawPerson(ctx: Ctx, body: Body): void {
  const [bx, by, bw, bh] = boxOf(body);
  // Draw the whole figure from its unclipped height (a box is clipped at the frame's edge).
  const h = body.h * H;
  const w = Math.max(10, bw * W);
  const cx = body.x * W;
  const foot = body.y * H;
  const top = foot - h;
  if (bh <= 0 || bx > 1 || by > 1) return;
  const look = body.look;
  const staff = body.role === "staff";
  const headR = Math.max(4, w * 0.2);
  const headY = top + headR * 1.1;

  if (!staff) {
    ctx.fillStyle = "rgba(30,20,10,0.18)";
    ctx.beginPath();
    ctx.ellipse(cx, foot, w * 0.5, Math.max(2, w * 0.12), 0, 0, Math.PI * 2);
    ctx.fill();
    // Legs.
    ctx.fillStyle = pick(TROUSERS, look, 3);
    const legTop = top + h * 0.6;
    roundRect(ctx, cx - w * 0.28, legTop, w * 0.24, foot - legTop, w * 0.08);
    ctx.fill();
    roundRect(ctx, cx + w * 0.04, legTop, w * 0.24, foot - legTop, w * 0.08);
    ctx.fill();
  }
  // Coat.
  const coat = staff ? "#fafaf7" : pick(COATS, look, 1);
  const torsoTop = headY + headR * 0.8;
  const torsoBottom = staff ? top + h * 1.12 : top + h * 0.66;
  ctx.fillStyle = coat;
  ctx.beginPath();
  ctx.moveTo(cx - w * 0.36, torsoTop + w * 0.08);
  ctx.quadraticCurveTo(cx - w * 0.46, torsoTop, cx - w * 0.3, torsoTop - w * 0.02);
  ctx.lineTo(cx + w * 0.3, torsoTop - w * 0.02);
  ctx.quadraticCurveTo(cx + w * 0.46, torsoTop, cx + w * 0.36, torsoTop + w * 0.08);
  ctx.lineTo(cx + w * 0.42, torsoBottom);
  ctx.lineTo(cx - w * 0.42, torsoBottom);
  ctx.closePath();
  ctx.fill();
  // Shading down one side, arms.
  ctx.fillStyle = staff ? "rgba(120,110,95,0.16)" : "rgba(0,0,0,0.14)";
  ctx.fillRect(cx + w * 0.18, torsoTop + w * 0.05, w * 0.2, torsoBottom - torsoTop - w * 0.05);
  ctx.fillStyle = staff ? "#ecebe6" : "rgba(0,0,0,0.12)";
  roundRect(ctx, cx - w * 0.5, torsoTop + w * 0.1, w * 0.14, (torsoBottom - torsoTop) * 0.8, w * 0.07);
  ctx.fill();
  roundRect(ctx, cx + w * 0.36, torsoTop + w * 0.1, w * 0.14, (torsoBottom - torsoTop) * 0.8, w * 0.07);
  ctx.fill();
  if (staff) {
    // Teal scrubs under the coat and the green cross badge.
    ctx.fillStyle = "#2a9d8f";
    ctx.beginPath();
    ctx.moveTo(cx - w * 0.13, torsoTop - w * 0.02);
    ctx.lineTo(cx + w * 0.13, torsoTop - w * 0.02);
    ctx.lineTo(cx, torsoTop + w * 0.28);
    ctx.closePath();
    ctx.fill();
    ctx.fillStyle = "#3bb273";
    const s = Math.max(3, w * 0.09);
    ctx.fillRect(cx - w * 0.26, torsoTop + w * 0.3, s, s * 3);
    ctx.fillRect(cx - w * 0.26 - s, torsoTop + w * 0.3 + s, s * 3, s);
  } else if (pick([0, 1, 2], look, 5) === 0) {
    // A bag on the shoulder.
    ctx.fillStyle = pick(["#6b4a2f", "#2f2f33", "#9b7b5b"], look, 9);
    roundRect(ctx, cx - w * 0.6, top + h * 0.42, w * 0.26, w * 0.3, 3);
    ctx.fill();
  }
  // Head: hair or a scarf from behind, a featureless face toward the camera.
  const scarf = !staff && pick([0, 1, 2, 3], look, 7) === 0;
  const facing = body.facing === "camera" || staff;
  ctx.fillStyle = facing ? pick(SKIN, look, 2) : scarf ? pick(SCARVES, look, 4) : pick(HAIR, look, 6);
  ctx.beginPath();
  ctx.arc(cx, headY, headR, 0, Math.PI * 2);
  ctx.fill();
  if (facing) {
    ctx.fillStyle = scarf ? pick(SCARVES, look, 4) : pick(HAIR, look, 6);
    ctx.beginPath();
    if (scarf) {
      ctx.arc(cx, headY, headR * 1.08, Math.PI * 0.95, Math.PI * 2.05);
      ctx.lineTo(cx + headR * 1.1, headY + headR * 0.9);
      ctx.lineTo(cx - headR * 1.1, headY + headR * 0.9);
    } else {
      ctx.arc(cx, headY - headR * 0.12, headR * 1.02, Math.PI * 1.02, Math.PI * 1.98);
    }
    ctx.closePath();
    ctx.fill();
  } else if (scarf) {
    ctx.fillStyle = pick(SCARVES, look, 4);
    ctx.beginPath();
    ctx.moveTo(cx - headR, headY);
    ctx.lineTo(cx + headR, headY);
    ctx.lineTo(cx + headR * 1.25, headY + headR * 1.6);
    ctx.lineTo(cx - headR * 1.25, headY + headR * 1.6);
    ctx.closePath();
    ctx.fill();
  }
}

function blackOut(ctx: Ctx, zones: readonly Zone[]): void {
  ctx.fillStyle = "#000";
  for (const zone of zones) if (zone.kind === "mask") {
    polygon(ctx, zone.points);
    ctx.fill();
  }
}

// ─── Frames ─────────────────────────────────────────────────────────────────

export interface DrawOptions {
  kind: SceneKind;
  variant: number;
  bodies: Body[];
  zones: Zone[];
  /** The agent's annotation for alert photos: zones, boxes, waits and the time. */
  annotate?: { caption: string; waitOver: number } | null;
}

let shared: { el: HTMLCanvasElement; ctx: Ctx } | null = null;

/** Draws one picture onto a canvas (the shared one unless given). */
export function drawScene(options: DrawOptions, target?: { el: HTMLCanvasElement; ctx: Ctx }): HTMLCanvasElement {
  shared ??= canvas();
  const { el, ctx } = target ?? shared;
  const bg = background(options.kind, options.variant);
  ctx.drawImage(bg.back, 0, 0, W, H);
  const staff = options.bodies.filter((body) => body.role === "staff" && options.kind === "counter");
  const others = options.bodies.filter((body) => !staff.includes(body)).sort((a, b) => a.y - b.y);
  for (const body of staff) drawPerson(ctx, body);
  if (bg.front) ctx.drawImage(bg.front, 0, 0, W, H);
  for (const body of others) drawPerson(ctx, body);
  vignette(ctx, options.kind === "storeroom" ? 0.3 : 0.2);
  blackOut(ctx, options.zones);
  if (options.annotate) annotate(ctx, options);
  return el;
}

export function jpegBase64(el: HTMLCanvasElement, quality = 0.8): string {
  return el.toDataURL("image/jpeg", quality).slice("data:image/jpeg;base64,".length);
}

export function jpegUrl(el: HTMLCanvasElement, quality = 0.82): string {
  return el.toDataURL("image/jpeg", quality);
}

function annotate(ctx: Ctx, options: DrawOptions): void {
  const { annotate: note, zones, bodies } = options;
  if (!note) return;
  for (const zone of zones) {
    if (zone.kind !== "queue" && zone.kind !== "staff") continue;
    polygon(ctx, zone.points);
    ctx.fillStyle = zone.kind === "queue" ? "rgba(246,160,107,0.14)" : "rgba(126,200,160,0.14)";
    ctx.fill();
    ctx.setLineDash([8, 6]);
    ctx.lineWidth = 2;
    ctx.strokeStyle = zone.kind === "queue" ? "rgba(246,160,107,0.9)" : "rgba(126,200,160,0.9)";
    ctx.stroke();
    ctx.setLineDash([]);
  }
  ctx.font = "600 15px ui-sans-serif, system-ui, sans-serif";
  ctx.textBaseline = "middle";
  for (const body of bodies) {
    const [x, y, w, h] = boxOf(body);
    if (w < 0.01) continue;
    const color = body.role === "staff" ? "#7ec8a0" : (body.wait ?? 0) >= note.waitOver ? "#ff8a6b" : "#ffc58a";
    ctx.strokeStyle = color;
    ctx.lineWidth = 3;
    roundRect(ctx, x * W, y * H, w * W, h * H, 8);
    ctx.stroke();
    if (body.wait !== null && body.role === "customer") {
      const text = clock(body.wait);
      const tw = ctx.measureText(text).width + 16;
      ctx.fillStyle = "rgba(20,16,12,0.78)";
      roundRect(ctx, x * W, y * H - 26, tw, 22, 11);
      ctx.fill();
      ctx.fillStyle = color;
      ctx.fillText(text, x * W + 8, y * H - 15);
    }
  }
  ctx.fillStyle = "rgba(10,8,6,0.62)";
  roundRect(ctx, 14, H - 40, ctx.measureText(note.caption).width + 24, 28, 8);
  ctx.fill();
  ctx.fillStyle = "#f3ece1";
  ctx.fillText(note.caption, 26, H - 26);
}

function clock(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

/** Records a few seconds of a scene into a WebM clip (MediaRecorder on the canvas; no camera). */
export async function recordClip(frameAt: (elapsed: number) => DrawOptions, seconds: number): Promise<{ url: string; poster: string }> {
  const target = canvas(W, H);
  drawScene(frameAt(0), target);
  const poster = jpegUrl(target.el);
  if (typeof MediaRecorder === "undefined" || typeof target.el.captureStream !== "function") throw new Error("no recorder");
  const stream = target.el.captureStream(24);
  const type = ["video/webm;codecs=vp9", "video/webm;codecs=vp8", "video/webm"].find((t) => MediaRecorder.isTypeSupported(t)) ?? "";
  const recorder = new MediaRecorder(stream, type ? { mimeType: type, videoBitsPerSecond: 2_000_000 } : undefined);
  const chunks: Blob[] = [];
  recorder.ondataavailable = (event) => event.data.size && chunks.push(event.data);
  const done = new Promise<void>((resolve) => (recorder.onstop = () => resolve()));
  recorder.start(250);
  const started = performance.now();
  await new Promise<void>((resolve) => {
    const tick = () => {
      const elapsed = (performance.now() - started) / 1000;
      drawScene(frameAt(elapsed), target);
      if (elapsed >= seconds) resolve();
      else setTimeout(tick, 40);
    };
    tick();
  });
  recorder.stop();
  await done;
  stream.getTracks().forEach((track) => track.stop());
  return { url: URL.createObjectURL(new Blob(chunks, { type: type || "video/webm" })), poster };
}
