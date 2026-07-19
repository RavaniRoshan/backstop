# Installing Backstop

Backstop is a Python package (library + `backstop` / `wedge` CLIs). This page
covers every supported install path, from a one-line end-user command to
air-gapped enterprise deployment.

> All commands below were verified against `backstop==0.4.0` by building the
> wheel and installing it into a clean virtual environment.

## End users

### One line (recommended)

```bash
pip install "backstop[anthropic]"
```

This installs the library plus Anthropic support in a single command. Use
`pip install backstop` if you only need OpenAI.

### One command (curl) — for users without pip/Python knowledge

If you don't have pip set up (or would rather not think about it), this single
command detects Python and installs Backstop for you:

```bash
curl -fsSL https://raw.githubusercontent.com/RavaniRoshan/backstop/main/install.sh | sh
```

It runs `pip install --user "backstop[anthropic]"` on your behalf. If Backstop
isn't on PyPI yet, it falls back to installing from the GitHub repo and tells
you so. Prefer to review the script before running it?

```bash
curl -fsSL https://raw.githubusercontent.com/RavaniRoshan/backstop/main/install.sh -o install.sh
sh install.sh
```

> This is a **convenience** path. The canonical, reproducible install is still
> `pip install "backstop[anthropic]"`. The script supports macOS and Linux;
> on Windows use Python's official installer + `pip`.

### Per-feature extras

```bash
pip install "backstop[metrics]"     # Prometheus metrics export
pip install "backstop[anthropic]"   # Claude / Anthropic clients
pip install "backstop[tokenizers]"  # tiktoken-based token estimation
pip install "backstop[fastapi]"     # FastAPI metrics app mount
```

Extras are combinable: `pip install "backstop[anthropic,metrics]"`.

### Run without a permanent install (pipx run)

If you have [pipx](https://pipx.pypa.io) installed, run either CLI without
permanently installing anything — ideal for a quick try or for CI:

```bash
pipx run backstop --help
pipx run wedge --help
pipx run wedge run task.yaml
```

`pipx run` fetches the wheel from PyPI, runs it in an ephemeral virtualenv, and
cleans up afterwards — no `curl | sh` bootstrap required.

### Isolated persistent CLI (pipx)

For the `backstop` and `wedge` commands specifically, install into an isolated
environment so they never conflict with your project dependencies:

```bash
pipx install backstop          # https://pipx.pypa.io
```

This exposes `backstop` and `wedge` on your `PATH`. Upgrade with
`pipx upgrade backstop`; remove with `pipx uninstall backstop`.

> `pipx` is itself a Python package (`pip install --user pipx`), so this path
> stays entirely within pip/PyPI — no external install script, no npm.

### From source / development

```bash
git clone https://github.com/RavaniRoshan/backstop.git
cd backstop
pip install -e ".[test,metrics,anthropic]"
```

## Enterprises

### Internal PyPI mirror (Artifactory / DevPi / internal registry)

Point pip at your mirror and install the same way:

```bash
pip install --index-url https://pypi.internal/simple "backstop[anthropic]"
# or, for the isolated CLI
pipx install --index-url https://pypi.internal/simple backstop
```

(`pypi.internal` stands in for Artifactory, DevPi, or any internal registry.)

Add `--extra-index-url https://pypi.org/simple` only if your mirror proxies
upstream.

### Pinned, reproducible installs

```bash
pip install "backstop[anthropic]==0.4.0"
# or, for the isolated CLI
pipx install "backstop==0.4.0"
```

For applications, commit a lockfile so every environment resolves identical
versions (e.g. `pip-compile` from `pip-tools`, or your org's lock workflow).

### Air-gapped / vendor supply chain

1. Build the wheel on a connected machine:
   ```bash
   python -m build --wheel   # produces dist/backstop-0.4.0-py3-none-any.whl
   ```
2. Transfer `backstop-0.4.0-py3-none-any.whl` (plus its dependency wheels) to
   the target and install:
   ```bash
   pip install ./backstop-0.4.0-py3-none-any.whl
   ```

### Server surface (metrics / Wedge harness)

The `backstop metrics` server and `wedge run` are long-running services. For
platform teams, containerize the image and run:

```bash
docker run -p 9090:9090 <your-registry>/backstop metrics
```

This mirrors how gateway tools (BricksLLM, LiteLLM) are consumed in production.

## Verifying your install

```bash
backstop --help     # lists: harness, metrics, real-openai, real-anthropic
wedge --help        # lists: run
python -c "import backstop; print(backstop.__version__)"
```

> Note: `wedge` with `provider: anthropic` requires the `anthropic` extra.
> On a base install you'll get a clear message:
> `pip install "backstop[anthropic]"`. OpenAI-provider Wedge works without it.
