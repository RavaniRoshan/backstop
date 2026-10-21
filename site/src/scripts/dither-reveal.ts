/**
 * The dither reveal.
 *
 * A port of Originkit's `dither-reveal` component to this site's rules:
 * no client framework, no runtime fetch, and a theme that is part of the
 * design rather than an afterthought. The WebGL shader is the component's own,
 * unchanged, with one uniform added — `uInvert` — so the same halftone reads
 * as a dark field on the dark theme and as an ink field on the light one.
 *
 * Three things it refuses to do:
 *
 * - It fetches nothing. The image is the repository's own dashboard
 *   screenshot, served from the site.
 * - It runs when the reader asked for no motion. The wave is autonomous
 *   animation, so it stops; the cursor reveal stays, because the cursor is
 *   the reader's own hand.
 * - It keeps the page readable. The canvas is decorative, it never takes a
 *   pointer event, and it falls back to the plain image when WebGL is not
 *   available.
 */
import { shaders } from "./dither-shaders";

const DEFAULTS = {
  fit: "cover" as "cover" | "contain",
  focusY: 50,
  ditherStyle: "bayer8" as "bayer8" | "lines" | "noise",
  dotSize: 5,
  revealRadius: 100,
  revealSoftness: 50,
  wave: true,
  waveSpeed: 82,
  waveDensity: 25,
};

const DITHER_INDEX: Record<string, number> = {
  bayer8: 0,
  lines: 1,
  noise: 2,
};

function clamp(value: string | null, min: number, max: number, fallback: number) {
  const parsed = parseFloat(value ?? "");
  if (!Number.isFinite(parsed)) return fallback;
  return Math.min(max, Math.max(min, parsed));
}

type Settings = {
  fit: number;
  focusY: number;
  ditherStyle: string;
  pixelSize: number;
  revealRadius: number;
  revealSoftness: number;
  waveSpeed: number;
  waveFrequency: number;
  waveAmplitude: number;
  waveMargin: number;
};

function settings(container: HTMLElement): Settings {
  const waveOn = container.dataset.ditherWave !== "off";
  const speed = waveOn ? clamp(container.dataset.ditherWaveSpeed ?? null, 1, 100, DEFAULTS.waveSpeed) / 100 : 0;
  const style = container.dataset.ditherStyle ?? DEFAULTS.ditherStyle;
  return {
    fit: (container.dataset.ditherFit ?? DEFAULTS.fit) === "contain" ? 1 : 0,
    focusY: clamp(container.dataset.ditherFocusY ?? null, 0, 100, DEFAULTS.focusY) / 100,
    ditherStyle: DITHER_INDEX[style] === undefined ? DEFAULTS.ditherStyle : style,
    pixelSize: clamp(container.dataset.ditherDotSize ?? null, 1, 20, DEFAULTS.dotSize) / 2,
    revealRadius: clamp(container.dataset.ditherRadius ?? null, 20, 600, DEFAULTS.revealRadius),
    revealSoftness: clamp(container.dataset.ditherSoftness ?? null, 0, 100, DEFAULTS.revealSoftness) / 100,
    waveSpeed: speed,
    waveFrequency: clamp(container.dataset.ditherDensity ?? null, 5, 100, DEFAULTS.waveDensity) / 10,
    waveAmplitude: speed * 0.4,
    waveMargin: speed * 0.4 * 0.15,
  };
}

/** Mount one dither reveal. Returns a teardown function. */
export function mountDitherReveal(container: HTMLElement): () => void {
  const canvas = container.querySelector<HTMLCanvasElement>("canvas");
  if (!canvas) return () => {};

  const imageUrl = container.dataset.ditherSrc ?? "";
  if (!imageUrl) return () => {};

  const gl = canvas.getContext("webgl", {
    antialias: false,
    premultipliedAlpha: false,
  });
  if (!gl) {
    // No WebGL: the plain image underneath is the whole effect.
    container.dataset.ditherFallback = "true";
    return () => {};
  }

  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  const compile = (type: number, source: string) => {
    const shader = gl.createShader(type);
    if (!shader) return null;
    gl.shaderSource(shader, source);
    gl.compileShader(shader);
    if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
      console.warn("DitherReveal shader:", gl.getShaderInfoLog(shader));
    }
    return shader;
  };

  const vs = compile(gl.VERTEX_SHADER, shaders.vertex);
  const fs = compile(gl.FRAGMENT_SHADER, shaders.fragment);
  if (!vs || !fs) return () => {};

  const program = gl.createProgram();
  if (!program) return () => {};
  gl.attachShader(program, vs);
  gl.attachShader(program, fs);
  gl.linkProgram(program);
  if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
    console.warn("DitherReveal link:", gl.getProgramInfoLog(program));
    return () => {};
  }
  gl.useProgram(program);
  gl.deleteShader(vs);
  gl.deleteShader(fs);

  const buffer = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
  const aPos = gl.getAttribLocation(program, "aPos");
  gl.enableVertexAttribArray(aPos);
  gl.vertexAttribPointer(aPos, 2, gl.FLOAT, false, 0, 0);

  const u = (name: string) => gl.getUniformLocation(program, name);
  const uTime = u("uTime");
  const uMouse = u("uMouse");
  const uMouseActive = u("uMouseActive");
  const uRevealRadius = u("uRevealRadius");
  const uRevealSoftness = u("uRevealSoftness");
  const uPixelSize = u("uPixelSize");
  const uDitherStyle = u("uDitherStyle");
  const uWaveSpeed = u("uWaveSpeed");
  const uWaveFrequency = u("uWaveFrequency");
  const uWaveAmplitude = u("uWaveAmplitude");
  const uWaveMargin = u("uWaveMargin");
  const uCanvasAspect = u("uCanvasAspect");
  const uImageAspect = u("uImageAspect");
  const uResolution = u("uResolution");
  const uFit = u("uFit");
  const uFocusY = u("uFocusY");
  const uInvert = u("uInvert");

  const texture = gl.createTexture();
  gl.bindTexture(gl.TEXTURE_2D, texture);
  gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, true);
  gl.texImage2D(
    gl.TEXTURE_2D,
    0,
    gl.RGBA,
    1,
    1,
    0,
    gl.RGBA,
    gl.UNSIGNED_BYTE,
    new Uint8Array([20, 20, 20, 255]),
  );
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);

  let imageAspect = 1.5;
  const image = new Image();
  image.onload = () => {
    if (image.naturalHeight > 0) imageAspect = image.naturalWidth / image.naturalHeight;
    gl.bindTexture(gl.TEXTURE_2D, texture);
    try {
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, image);
    } catch {
      /* The placeholder texture stays; the fallback image is behind it. */
    }
  };
  image.onerror = () => console.warn("DitherReveal: image failed to load:", imageUrl);
  image.src = imageUrl;

  const mouse = { x: 0.5, y: 0.5, active: 0, target: 0, entered: false };
  let rect = container.getBoundingClientRect();

  const measure = () => {
    rect = container.getBoundingClientRect();
  };

  /* The canvas never takes a pointer event, so the cursor is tracked on the
     window and mapped onto the canvas by hand. That way the reveal works
     over the headline and over the buttons, not only over bare canvas. */
  const onMove = (event: PointerEvent) => {
    const x = event.clientX - rect.left;
    const y = event.clientY - rect.top;
    const inside = x >= 0 && y >= 0 && x <= rect.width && y <= rect.height;
    if (!inside) {
      mouse.target = 0;
      mouse.entered = false;
      return;
    }
    mouse.x = x / Math.max(rect.width, 1);
    mouse.y = 1 - y / Math.max(rect.height, 1);
    mouse.entered = true;
    mouse.target = 1;
  };
  const onLeaveWindow = () => {
    mouse.target = 0;
    mouse.entered = false;
  };

  window.addEventListener("pointermove", onMove, { passive: true });
  window.addEventListener("blur", onLeaveWindow);
  window.addEventListener("scroll", measure, { passive: true });

  const resize = () => {
    const dpr = Math.min(window.devicePixelRatio || 1, 1.5);
    canvas.width = Math.max(1, Math.floor(container.clientWidth * dpr));
    canvas.height = Math.max(1, Math.floor(container.clientHeight * dpr));
    gl.viewport(0, 0, canvas.width, canvas.height);
    measure();
  };
  resize();
  const ro = new ResizeObserver(resize);
  ro.observe(container);

  let inView = true;
  const io = new IntersectionObserver(
    ([entry]) => {
      inView = entry.isIntersecting;
    },
    { threshold: 0.01 },
  );
  io.observe(container);

  const live = settings(container);
  const start = performance.now();
  let raf = 0;
  let lastTheme = "";

  const render = () => {
    raf = requestAnimationFrame(render);
    if (!inView) return;

    const now = performance.now();
    mouse.active += (mouse.target - mouse.active) * 0.08;

    /* The same halftone has to read on both themes. On the dark theme the
       dither is ink on night; on the light one it is night on paper. The
       theme is read from the document, which is where the site's own theme
       toggle puts it. */
    const theme = document.documentElement.dataset.theme ?? "light";
    if (theme !== lastTheme) {
      lastTheme = theme;
      gl.uniform1f(uInvert, theme === "light" ? 1 : 0);
    }

    const wave = reduced ? 0 : live.waveSpeed;

    gl.uniform1f(uTime, (now - start) / 1000);
    gl.uniform2f(uMouse, mouse.x, mouse.y);
    gl.uniform1f(uMouseActive, mouse.entered ? mouse.active : 0);
    gl.uniform1f(uRevealRadius, live.revealRadius);
    gl.uniform1f(uRevealSoftness, live.revealSoftness);
    gl.uniform1f(uPixelSize, live.pixelSize);
    gl.uniform1f(uDitherStyle, DITHER_INDEX[live.ditherStyle] ?? 0);
    gl.uniform1f(uWaveSpeed, wave);
    gl.uniform1f(uWaveFrequency, live.waveFrequency);
    gl.uniform1f(uWaveAmplitude, wave * 0.4);
    gl.uniform1f(uWaveMargin, wave * 0.4 * 0.15);
    gl.uniform1f(uCanvasAspect, canvas.width / canvas.height);
    gl.uniform1f(uImageAspect, imageAspect);
    gl.uniform2f(uResolution, container.clientWidth || 1, container.clientHeight || 1);
    gl.uniform1f(uFit, live.fit);
    gl.uniform1f(uFocusY, live.focusY);
    gl.drawArrays(gl.TRIANGLES, 0, 3);
  };
  render();

  return () => {
    cancelAnimationFrame(raf);
    ro.disconnect();
    io.disconnect();
    image.onload = null;
    image.onerror = null;
    window.removeEventListener("pointermove", onMove);
    window.removeEventListener("blur", onLeaveWindow);
    window.removeEventListener("scroll", measure);
    gl.deleteProgram(program);
    gl.deleteBuffer(buffer);
    gl.deleteTexture(texture);
  };
}

/** Mount every dither reveal on the page. */
export function mountDitherReveals(): void {
  document
    .querySelectorAll<HTMLElement>("[data-dither-reveal]")
    .forEach((container) => mountDitherReveal(container));
}
