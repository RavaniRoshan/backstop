/**
 * The easing the loader borrows from Originkit's component.
 *
 * Small, exact, and worth keeping in one place: the loader's curve is the
 * component's own, and a curve that drifts is a different animation.
 */

export const clamp = (x: number, min = 0, max = 1): number =>
  x < min ? min : x > max ? max : x;

/** The normalised position of `x` between `a` and `b`. */
export const seg = (x: number, a: number, b: number): number =>
  clamp((x - a) / Math.max(1e-6, b - a));

export const lerp = (a: number, b: number, t: number): number => a + (b - a) * t;

export const outCubic = (x: number): number => 1 - Math.pow(1 - x, 3);

export const inCubic = (x: number): number => x * x * x;

export const inOutCubic = (x: number): number =>
  x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2;

export const inOutQuart = (x: number): number =>
  x < 0.5 ? 8 * x * x * x * x : 1 - Math.pow(-2 * x + 2, 4) / 2;
