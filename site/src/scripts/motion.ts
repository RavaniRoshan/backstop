/**
 * The page's only moving parts.
 *
 * Three rules, and they are the whole of it:
 *
 * - Nothing moves if the reader asked for it not to. `prefers-reduced-motion`
 *   is checked once, and the reduced path shows everything at once and
 *   animates nothing.
 * - Nothing is hidden unless JavaScript is going to show it again. The hidden
 *   state lives behind a flag the page sets before the first paint, so a
 *   reader with no JavaScript sees the whole page, in full, immediately.
 * - Everything is revealed once. An element that has been revealed says so,
 *   and a second pass leaves it alone.
 */
import { animate, inView, stagger } from "motion";

/** The house easing: a fast start and a long, quiet settle. */
const EASE = [0.32, 0.72, 0, 1] as const;

const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

/** Say that an element has been shown, so the CSS stops hiding it. */
function show(el: Element): void {
  el.setAttribute("data-revealed", "");
}

/**
 * How late in its group an element starts: its order among the marked
 * siblings it shares a parent with. The features list, the four plain-words
 * cards and the four lanes each cascade down their own column rather than
 * all at once.
 */
function orderInGroup(el: HTMLElement): number {
  const parent = el.parentElement;
  if (!parent) return 0;
  const peers = Array.from(parent.children).filter((child) =>
    child.hasAttribute("data-reveal"),
  );
  const index = peers.indexOf(el);
  return index > 0 ? index : 0;
}

/** Count a number up to the value it carries. */
function countUp(el: HTMLElement): void {
  const raw = el.dataset.count;
  if (raw === undefined) return;
  const target = Number(raw);
  if (!Number.isFinite(target)) return;
  const decimals = Number(el.dataset.decimals ?? "0");
  if (reduced || target === 0) {
    el.textContent = target.toFixed(decimals);
    return;
  }
  animate(0, target, {
    duration: 0.9,
    ease: EASE,
    onUpdate: (value: number) => {
      el.textContent = value.toFixed(decimals);
    },
  });
}

/** Bring one element in. */
function reveal(el: HTMLElement): void {
  const group = el.dataset.reveal ?? "";

  /* The strip of marks is a group of its own: the row fades in as one block,
     and then the marks inside it arrive one after another. */
  if (group === "chips") {
    const chips = Array.from(el.children) as HTMLElement[];
    show(el);
    animate(
      chips,
      { opacity: [0, 1], transform: ["translateY(6px)", "translateY(0px)"] },
      { duration: 0.42, ease: EASE, delay: stagger(0.035) },
    );
    return;
  }

  show(el);
  animate(
    el,
    { opacity: [0, 1], transform: ["translateY(14px)", "translateY(0px)"] },
    { duration: 0.55, ease: EASE, delay: orderInGroup(el) * 0.05 },
  );

  el.querySelectorAll<HTMLElement>("[data-count]").forEach(countUp);
}

/** Bring an element in the moment it scrolls into view. */
function onScroll(selector: string): void {
  const targets = Array.from(document.querySelectorAll<HTMLElement>(selector));
  if (!targets.length) return;
  if (reduced) {
    targets.forEach(show);
    return;
  }
  const seen = new WeakSet<Element>();
  inView(
    targets,
    (element) => {
      const el = element as HTMLElement;
      if (seen.has(el)) return;
      seen.add(el);
      reveal(el);
    },
    { amount: 0.15 },
  );
}

/** Bring a group in on load, in order. The hero does not wait for a scroll. */
function onLoad(selector: string): void {
  const targets = Array.from(document.querySelectorAll<HTMLElement>(selector));
  if (!targets.length) return;
  if (reduced) {
    targets.forEach(show);
    return;
  }
  targets.forEach(show);
  animate(
    targets,
    { opacity: [0, 1], transform: ["translateY(16px)", "translateY(0px)"] },
    { duration: 0.65, ease: EASE, delay: stagger(0.07) },
  );
}

/* The hero enters as soon as the page does. Everything else waits for the
   reader to arrive at it. */
onLoad('[data-reveal="hero"]');
onScroll("[data-reveal]:not([data-reveal='hero'])");
