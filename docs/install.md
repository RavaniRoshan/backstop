# Installing Backstop

Backstop's Python distribution is `backstop-ai`. The import remains
`backstop`, and the console commands remain `backstop` and `wedge`.
Python 3.10 or newer is required.

> **0.6.0 is published.** The registry commands below are the supported
> install path: `backstop-ai` 0.6.0 is on PyPI, `backstop-ai` 0.6.0 is on npm,
> and the `v0.6.0` GitHub Release carries the wheel and sdist. The default
> branch is unreleased work past that tag. The PyPI name `backstop` belongs to
> an unrelated project.
>
> SDK compatibility is bounded, not open-ended. Below the declared floors
> (`openai>=2.37`, `anthropic>=0.98`) the provider SDK catches Backstop's
> `BudgetExceededError` and re-raises it as `APIConnectionError`, so budget
> enforcement becomes invisible to your code; older SDKs additionally break
> against `httpx>=0.28`. Within the tested range that relabelling does not
> happen. Installing successfully still does not prove provider
> compatibility — run `backstop verify` for that, and read its documented
> limits in [Checking your install](install.md#checking-your-install).
>
> The npm package `backstop-ai` is a different, partial TypeScript port of this
> project. `pip install backstop-ai` and `npm install backstop-ai` do not give
> you the same code.

## End users

### One line

```bash
pip install "backstop-ai[anthropic]"
```

This installs the library plus the Anthropic SDK dependency. Use
`pip install backstop-ai` for the base dependencies, including OpenAI.

### Convenience installer

The installer detects Python and invokes pip. It is not a substitute for
resolving the compatibility limitations above. Review it before running:

```bash
curl -fsSL https://raw.githubusercontent.com/RavaniRoshan/backstop/main/install.sh -o install.sh
sh install.sh
```

It runs `python3 -m pip install --user --upgrade "backstop-ai[anthropic]==0.6.0"`.
If the PyPI install fails, it falls back to the GitHub repository's current
source, which is not a pinned release. Set `BACKSTOP_NO_GITFALLBACK=1` to
fail instead. The 0.6.0 release verification installed from PyPI directly with
pip, not through this script.

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

If you have [pipx](https://pipx.pypa.io) installed, run
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

### Pinned installs

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
backstop verify
```

The first three check CLI entry points and the import version. They say nothing
about provider compatibility. `backstop verify` is the command that does: it
runs eight offline checks against a local mock transport — wrap pipeline,
budget block, overhead, cache, per-agent isolation, hierarchical budgets, shadow
mode — and exits 0 with no network and no key.

### `backstop doctor` — what it proves, and its one known defect

`backstop doctor` is a **wrap-and-import smoke test**. It builds mock clients,
wraps them, and confirms HTTP-family detection resolves. It does **not** send a
request through the wrapped transport, so it cannot prove enforcement works. Use
`backstop verify` for that.

Known defect: `doctor` imports `httpx2` unconditionally in its wrap smoke test,
but `httpx2` is not a declared dependency — it only arrives as a dependency of
`openai>=3` / `anthropic>=1`. On an install that resolves to the older SDK
family, so that `httpx2` is absent, the import fails and `doctor` exits 1 with a
`ModuleNotFoundError` traceback. That is a bug in `doctor`, not a broken install:

```bash
python -c "import httpx2" && echo "httpx2 present" || echo "doctor will exit 1 here"
```

`backstop verify` is unaffected by this and is the command to trust.

### Probing the live provider

`backstop verify --live` adds one network check: a `GET /models` against the
provider. It resolves the key per provider — `OPENAI_API_KEY` for
`--provider openai`, `ANTHROPIC_API_KEY` for `--provider anthropic` — with an
explicit `--api-key-env` overriding the default, and sends provider-correct
auth headers. If `--base-url` points somewhere other than the provider's default
host, `verify` warns on stderr naming the destination, because your provider
credential is about to be sent there.

A 200 proves the key exists. It does **not** prove scope, quota, or model
entitlement.

One flag trap: `--offline` is accepted but inert. The runner only reads
`--live`, so passing `--offline` together with `--live` still performs the live
probe. Omit `--live` for no network.

> `wedge` with `provider: anthropic` requires the `anthropic` extra:
> `pip install "backstop-ai[anthropic]"`. The extra installs the SDK; the
> enforcement floors documented in
> [compatibility](compatibility.md#providers) are what make the error catchable.
