# Showcase build — the college-demo reel

A visual walkthrough for showing a user how the product is actually used. Built
from **VHS** (real terminal recording: real typing, real cursor, real output) for
the terminal acts, and **Playwright** (real dashboard, real workload) for the
dashboard acts, composited into one timeline and exported as an MP4 master with a
GIF derived from it.

## On the demo-gif skill

`demo-gif` is a forensic reproduction spec for one reference GIF, and its hard
constraints are the opposite of what a showcase needs:

| demo-gif spec | what a showcase needs |
|---|---|
| 10 fps | 30 fps |
| 256-colour GIF89a palette | full colour |
| "no fades, no easing" | smooth transitions |
| "no cursor blink", no per-character typing | a cursor that moves as you type |
| discrete scroll jumps | continuous motion |

Those constraints are why the previous set looked glitchy rather than crisp, so
this build takes the skill's *composition language* — the floating rounded window
over a margin, the window bar, the beat grid, the bottom input and status bar,
the pill overlays — and authors at 30 fps in full colour with real motion.

## What is real, and what could not be

Real, and verified: the VHS toolchain records genuine typing and a genuine
cursor; a fresh virtualenv **actually installs `backstop-ai` from PyPI inside the
recording**, so the install line is not staged; and every command's output is the
command's real output.

One thing cannot be shown: a **successful live completion**, because that needs a
real provider key, which this build does not have and should not use. The offline
path is the honest substitute and the product already ships it — `backstop demo`
labels itself "100% offline (mock transport, zero API keys)" and prints the
unprotected-versus-wrapped comparison. An earlier attempt at a live call recorded
a 401 traceback, which is *correct* behaviour — the guardrail let the request
through and the provider rejected the fake key — but it is a bad frame, and it
proves the point about honesty: a recording cannot be tidied after the fact.

## Two VHS parser constraints worth knowing

- `Set Height` / `Set Width` take a space, not `SetFontSize` camelCase.
- The tape parser splits on `;` **even inside quotes**, so
  `Type "python -c \"import x; print(x)\""` fails to parse. Put the command in a
  script file and run that instead — see `show_version.py`.

## Acts

| act | source | what it shows |
|---|---|---|
| 1 | VHS | fresh venv, real install from PyPI, the real `__version__` |
| 2 | VHS | `backstop demo` — the same 8 iterations unwrapped vs wrapped |
| 3 | Playwright | the dashboard draining a real budget |
| 4 | Playwright | the guardrail firing, prevented/s rising |
| 5 | Playwright | per-agent ceilings, the sessions table |
| 6 | VHS | the ledger and the charge-back |
| 7 | VHS | reconciliation against a statement |

## Output

`backstop-showcase.mp4` is the master: 1920x1080, 30 fps, H.264, faststart.
`backstop-showcase.gif` is derived from it, not authored separately — a GIF is
256 colours and cannot be the master, so the MP4 is what you project and the GIF
is the convenience preview.
