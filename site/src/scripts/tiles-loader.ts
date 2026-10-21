/**
 * The tiles loader.
 *
 * A port of Originkit's `tiles-loader` component to this site's rules: no
 * client framework, nothing fetched at runtime, and a theme that is part of
 * the design rather than an afterthought.
 *
 * The component arrives as a React component that waits fourteen seconds and
 * shows an editorial loader over the page. The fourteen seconds is the
 * component's own default for a preview surface, and it is far too long to
 * stand between a reader and a page — so the wait here is short, the load
 * curve is the component's own, and the page underneath is already rendered
 * when the loader lifts.
 *
 * Four things it refuses to do:
 *
 * - It cannot trap a reader who has no JavaScript. The markup carries a
 *   `<noscript>` rule that removes it, and the driver has a failsafe.
 * - It does not appear to a reader who asked for no motion. The page simply
 *   arrives.
 * - It does not own the page. It is an overlay: the site is rendered behind
 *   it the whole time, and the loader's job is to lift.
 * - It does not use a font the site has not already self-hosted.
 */
import { clamp, lerp, outCubic, seg, inOutCubic } from "./easing";

const SHORT_SIDE = 7;
const INK_WINDOW = 0.04;
const FADE_S = 0.35;

/** A small deterministic random, so the loader is the same every time. */
function rand(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/**
 * The progress curve, with the stops a real loader has.
 *
 * A counter that slides evenly from 0 to 100 says "we are animating". A
 * counter that reaches 50%, waits, reaches 78%, waits, reaches 82%, waits,
 * and only then finishes says "there is still work happening". Those three
 * stops are where an honest loader stalls: the page is mostly there, and the
 * last of it is not.
 *
 * The holds are a little longer at the end than in the middle, because the
 * end is where the reader is looking hardest.
 */
const STOPS: { to: number; move: number; hold: number }[] = [
  { to: 0.5, move: 0.26, hold: 0.24 },
  { to: 0.78, move: 0.16, hold: 0.3 },
  { to: 0.82, move: 0.1, hold: 0.3 },
  { to: 1, move: 0.17, hold: 0 },
];

/** The curve, in seconds. */
function loaderCurve(fillS: number): (t: number) => number {
  const total = STOPS.reduce((sum, stop) => sum + stop.move + stop.hold, 0);
  const segments = STOPS.map((stop) => ({
    from: 0,
    to: stop.to,
    move: (stop.move / total) * fillS,
    hold: (stop.hold / total) * fillS,
  }));
  segments.reduce((from, segment, index) => {
    segments[index].from = from;
    return segment.to;
  }, 0);

  return (t: number) => {
    let cursor = 0;
    for (const segment of segments) {
      if (t < cursor + segment.move) {
        const x = (t - cursor) / Math.max(1e-3, segment.move);
        return segment.from + (segment.to - segment.from) * x * x * (3 - 2 * x);
      }
      cursor += segment.move;
      /* The stop: the counter stays exactly here for a while. */
      if (t < cursor + segment.hold) return segment.to;
      cursor += segment.hold;
    }
    return 1;
  };
}

/** How much of the page is actually here: the images, and the fonts. */
function realLoad(): number {
  if (document.readyState === "complete") return 1;
  const images = document.images;
  let done = 0;
  for (let i = 0; i < images.length; i++) if (images[i].complete) done++;
  const fraction = images.length ? done / images.length : 1;
  const fonts = document.fonts && document.fonts.status === "loaded" ? 1 : 0;
  return Math.min(0.95, 0.15 + 0.6 * fraction + 0.2 * fonts);
}

export interface TilesLoaderOptions {
  /** The shortest the loader may stay up, in seconds. */
  minTime?: number;
  /** How long the tiles take to shrink away, in seconds. */
  revealTime?: number;
  /** Called once the page is revealed. */
  onComplete?: () => void;
}

/** Mount the loader. Returns a function that lifts it immediately. */
export function mountTilesLoader(
  root: HTMLElement,
  options: TilesLoaderOptions = {},
): () => void {
  const minTime = options.minTime ?? 1.5;
  const revealTime = options.revealTime ?? 0.6;

  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  let finished = false;
  let raf = 0;

  const lift = () => {
    if (finished) return;
    finished = true;
    cancelAnimationFrame(raf);
    root.style.transition = `opacity ${FADE_S}s ease`;
    root.style.opacity = "0";
    root.style.pointerEvents = "none";
    window.setTimeout(() => root.remove(), FADE_S * 1000);
    document.documentElement.dataset.loading = "done";
    options.onComplete?.();
    document.dispatchEvent(new CustomEvent("backstop:ready"));
  };

  /* A reader who asked for no motion gets the page, not a performance. */
  if (reduced) {
    lift();
    return lift;
  }

  const grid = root.querySelector<HTMLElement>(".tiles-loader-grid");
  const countEl = root.querySelector<HTMLElement>(".tiles-loader-count");
  const numEl = root.querySelector<HTMLElement>(".tiles-loader-num");
  if (!grid || !countEl || !numEl) {
    lift();
    return lift;
  }

  let cols = 0;
  let rows = 0;
  let tiles: HTMLElement[] = [];
  let papers: HTMLElement[] = [];
  let order: number[] = [];

  const build = () => {
    const w = root.offsetWidth;
    const h = root.offsetHeight;
    if (!w || !h) return;
    const cell = Math.min(w, h) / SHORT_SIDE;
    const nextCols = Math.max(1, Math.round(w / cell));
    const nextRows = Math.max(1, Math.round(h / cell));
    if (nextCols === cols && nextRows === rows && tiles.length) return;
    cols = nextCols;
    rows = nextRows;

    const count = cols * rows;
    const r = rand(count * 7919 + 13);
    order = Array.from({ length: count }, () => r() * (1 - INK_WINDOW));

    tiles = [];
    papers = [];
    const fragment = document.createDocumentFragment();
    for (let i = 0; i < count; i++) {
      const c = i % cols;
      const row = Math.floor(i / cols);
      const tile = document.createElement("div");
      tile.className = "tiles-loader-tile";
      tile.style.left = `${(c * 100) / cols}%`;
      tile.style.top = `${(row * 100) / rows}%`;
      tile.style.width = `calc(${100 / cols}% + 1px)`;
      tile.style.height = `calc(${100 / rows}% + 1px)`;
      const paper = document.createElement("div");
      paper.className = "tiles-loader-paper";
      tile.appendChild(paper);
      fragment.appendChild(tile);
      tiles.push(tile);
      papers.push(paper);
    }
    grid.replaceChildren(fragment);
  };

  build();
  const ro = new ResizeObserver(() => {
    build();
  });
  ro.observe(root);

  let t = 0;
  let progress = 0;
  let revealAt = -1;
  const fillS = Math.max(0.5, minTime);
  const curve = loaderCurve(fillS);

  const draw = () => {
    const reveal = revealAt < 0 ? 0 : clamp((t - revealAt) / revealTime, 0, 1);
    for (let i = 0; i < papers.length; i++) {
      papers[i].style.opacity = String(1 - seg(progress, order[i], order[i] + INK_WINDOW));
      const tile = tiles[i];
      const c = i % cols;
      const row = Math.floor(i / cols);
      const d =
        0.5 * (cols > 1 ? c / (cols - 1) : 0) + 0.5 * (rows > 1 ? (rows - 1 - row) / (rows - 1) : 0);
      const e = inOutCubic(seg(reveal, d * 0.55, d * 0.55 + 0.45));
      tile.style.transform = `scale(${1 - e})`;
    }
    const digits = String(Math.round(progress * 100));
    if (numEl.textContent !== digits) numEl.textContent = digits;
    countEl.style.opacity = String(outCubic(seg(t, 0.1, 0.8)) * (1 - seg(reveal, 0, 0.15)));
  };

  let last = -1;
  const tick = (now: number) => {
    const dt = last < 0 ? 0 : Math.min(0.05, (now - last) / 1000);
    last = now;
    t += dt;
    if (revealAt < 0) {
      const target = Math.min(curve(t), realLoad());
      /* The rate limit is high enough that the curve governs and the stops
         land exactly where they are supposed to. It is only a floor, for the
         case where the curve jumps. */
      progress = target >= 1 ? 1 : Math.min(target, progress + dt * 6);
      if (progress >= 1 && t >= fillS) {
        revealAt = t;
        /* The tiles are about to shrink away, and what they uncover has to
           be the page. While the loader was filling, its own background was
           the page's background; now it has to stop being one. */
        root.style.background = "transparent";
      }
    }
    draw();
    if (revealAt >= 0 && t - revealAt >= revealTime) {
      lift();
      return;
    }
    raf = requestAnimationFrame(tick);
  };
  raf = requestAnimationFrame(tick);

  return lift;
}
