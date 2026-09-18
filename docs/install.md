# Installing Backstop

Backstop's Python distribution is `backstop-ai`. The import remains
`backstop`, and the console commands remain `backstop` and `wedge`.
Python 3.10 or newer is required.

> **0.6.0 is unreleased.** PyPI publication and installation from PyPI have
> not been verified. The registry commands below are for use after publication;
> until then, use the source instructions. The PyPI name `backstop` belongs to
> an unrelated project.
>
> SDK compatibility is unresolved: current Anthropic SDKs can reject wrapping,
> and SDKs can relabel Backstop enforcement errors as connection errors.
> Dependency bounds have not yet been changed. Installing successfully does
> not prove provider compatibility or budget enforcement.

## End users

### One line (after publication)

```bash
pip install "backstop-ai[anthropic]"
```

This installs the library plus the Anthropic SDK dependency. Use
`pip install backstop-ai` for the base dependencies, including OpenAI.

### Convenience installer (after publication)

The installer detects Python and invokes pip. It is not a substitute for
resolving the compatibility limitations above. Review it before running:

```bash
curl -fsSL https://raw.githubusercontent.com/RavaniRoshan/backstop/main/install.sh -o install.sh
sh install.sh
```

It runs `python3 -m pip install --user --upgrade "backstop-ai[anthropic]==0.6.0"`.
If the PyPI install fails, it falls back to the GitHub repository's current
source, which is not a pinned release. Set `BACKSTOP_NO_GITFALLBACK=1` to
fail instead. This installer has not been run as part of 0.6.0 verification.

> The script supports macOS and Linux; on Windows use Python's official
> installer and `pip`. Prefer a virtual environment and the pip commands above
> over the convenience installer.

### Per-feature extras

```bash
pip install "backstop-ai[metrics]"     # Prometheus metrics export
pip install "backstop-ai[anthropic]"   # Anthropic SDK dependency
pip install "backstop-ai[tokenizers]"  # tiktoken-based token estimation
pip install "backstop-ai[fastapi]"     # FastAPI dependency
pip install "backstop-ai[redis]"       # Redis dependency
pip install "backstop-ai[otel]"        # OpenTelemetry metrics export
```

Extras are combinable: `pip install "backstop-ai[anthropic,metrics]"`.

### Run without a permanent install (pipx run)

After publication, if you have [pipx](https://pipx.pypa.io) installed, run
either CLI in an ephemeral virtual environment. Specify the distribution
explicitly because it differs from the console command names:

```bash
pipx run --spec backstop-ai backstop --help
pipx run --spec backstop-ai wedge --help
pipx run --spec "backstop-ai[anthropic]" wedge run task.yaml
```

`pipx run` downloads the distribution from PyPI and uses a temporary environment
(which pipx may cache) rather than installing the CLI permanently.

### Isolated persistent CLI (pipx)

For the `backstop` and `wedge` commands specifically, install into an isolated
environment so they do not share your project dependencies:

```bash
pipx install backstop-ai          # https://pipx.pypa.io
```

This exposes `backstop` and `wedge` on your `PATH`. Upgrade with
`pipx upgrade backstop-ai`; remove with `pipx uninstall backstop-ai`.

> `pipx` is itself a Python package (`pip install --user pipx`), so this path
> stays entirely within pip/PyPI — no external install script, no npm.

### From source / development

```bash
git clone https://github.com/RavaniRoshan/backstop.git
cd backstop
python -m venv .venv
# macOS/Linux; on Windows use .venv\Scripts\activate
. .venv/bin/activate
python -m pip install -e ".[test,metrics,anthropic]"
```

Source installation does not resolve the SDK compatibility limitations above.

## Enterprises

### Internal PyPI mirror (Artifactory / DevPi / internal registry)

Once your mirror contains `backstop-ai` and its dependencies, point pip at it:

```bash
pip install --index-url https://pypi.internal/simple "backstop-ai[anthropic]"
# or, for the isolated CLI
pipx install --index-url https://pypi.internal/simple backstop-ai
```

(`pypi.internal` stands in for Artifactory, DevPi, or any internal registry.)

Configure upstream access through your mirror according to your organization's
package-source policy.

### Pinned installs (after publication)

```bash
pip install "backstop-ai[anthropic]==0.6.0"
# or, for the isolated CLI
pipx install "backstop-ai==0.6.0"
```

Pinning Backstop alone does not pin dependencies. For applications, commit a
lockfile so environments resolve identical versions (e.g. `pip-compile` from
`pip-tools`, or your organization's lock workflow).

### Air-gapped / vendor supply chain

1. Build the wheel from this source checkout on a connected machine with
   the `build` package installed:
   ```bash
   python -m build --wheel   # expected: dist/backstop_ai-0.6.0-py3-none-any.whl
   ```
2. Transfer `backstop_ai-0.6.0-py3-none-any.whl` plus its dependency wheels to
   a `wheelhouse` directory on the target and install without index access:
   ```bash
   pip install --no-index --find-links ./wheelhouse "backstop-ai==0.6.0"
   ```

### Server surface (metrics / Wedge harness)

The `backstop metrics` server and `wedge run` are long-running services. For
platform teams, containerize the image and run:

```bash
docker run -p 9090:9090 <your-registry>/backstop metrics
```

This is an example for an image you build, not a published Backstop image.

## Checking your install

```bash
backstop --help
wedge --help
python -c "import backstop; print(backstop.__version__)"
```

These commands check CLI entry points and the import version, not provider
compatibility. The current `backstop doctor` smoke test is not sufficient to
prove SDK wrapping or enforcement works.

> `wedge` with `provider: anthropic` requires the `anthropic` extra:
> `pip install "backstop-ai[anthropic]"`. The extra installs the SDK; it does
> not resolve the known wrapping incompatibility.
