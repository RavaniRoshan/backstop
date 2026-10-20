#!/bin/sh
# Backstop — one-command installer (convenience / secondary path).
#
# Canonical install remains:   pip install "backstop-ai[anthropic]"
# 0.8.0 is the version being published here: PyPI `backstop-ai`, the
# `v0.8.0` GitHub Release, and npm `backstop-ai`. The Git fallback below installs current source from
# main, which is unreleased work past the tag, not a pinned release.
# Review this script and /docs/install.md before running it.
#
#   curl -fsSL https://raw.githubusercontent.com/RavaniRoshan/backstop/main/install.sh | sh
#
# Safer "review, then run" flow:
#   curl -fsSL https://raw.githubusercontent.com/RavaniRoshan/backstop/main/install.sh -o install.sh
#   sh install.sh
#
# Env overrides:
#   BACKSTOP_EXTRAS=anthropic,metrics   extras to install (default: anthropic)
#   BACKSTOP_NO_GITFALLBACK=1           don't fall back to GitHub if PyPI fails
#   BACKSTOP_SHA_URL=...               URL for .sha256 checksum file (default: same URL + .sha256)
#   BACKSTOP_SKIP_CHECKSUM=1           skip checksum verification (not recommended)
#   BACKSTOP_VENV=...                  directory for the fallback virtualenv
set -eu

BOLD=''
NORM=''
if [ -t 1 ]; then BOLD='\033[1m'; NORM='\033[0m'; fi
info() { printf "${BOLD}==>${NORM} %s\n" "$1"; }
warn() { printf "!! %s\n" "$1" >&2; }

# Verify the installer's own checksum, when that is possible.
#
# It is only possible when the script is a *file*: a piped script has already
# been executed by the time anything here runs, so verifying it would be
# theatre. The previous version of this block copied "$0" — which, for the
# documented `curl | sh` flow, is the shell rather than the script — and then
# compared the shell's checksum against the script's, so a checksum that
# existed would have failed every install. And the `.sha256` file this block
# fetches was never published, so the block could only ever warn.
if [ "${BACKSTOP_SKIP_CHECKSUM:-0}" != "1" ]; then
  SCRIPT_URL="${BACKSTOP_INSTALLER_URL:-https://raw.githubusercontent.com/RavaniRoshan/backstop/main/install.sh}"
  SHA_URL="${BACKSTOP_SHA_URL:-${SCRIPT_URL}.sha256}"
  if [ ! -f "$0" ]; then
    warn "This script was piped, so it cannot verify its own checksum."
    warn "For a verified install, download it first, check it, then run it:"
    warn "    curl -fsSL ${SCRIPT_URL} -o install.sh"
    warn "    sh install.sh"
  else
    TMPDIR="$(mktemp -d)"
    if command -v curl >/dev/null 2>&1; then
      FETCH="curl -fsSL"
    elif command -v wget >/dev/null 2>&1; then
      FETCH="wget -qO-"
    else
      warn "Neither curl nor wget found; skipping checksum verification."
      FETCH=""
    fi
    if [ -n "$FETCH" ]; then
      if $FETCH "$SHA_URL" -o "$TMPDIR/install.sh.sha256" 2>/dev/null; then
        cp "$0" "$TMPDIR/install.sh"
        # The checksum runs in a subshell: the earlier version did `cd
        # "$TMPDIR"` in the main shell and then deleted that directory, so
        # every later relative path was resolved against a directory that no
        # longer existed.
        if command -v sha256sum >/dev/null 2>&1; then
          if (cd "$TMPDIR" && sha256sum -c install.sh.sha256 >/dev/null 2>&1); then
            info "Installer checksum verified."
          else
            warn "Installer checksum mismatch! Aborting."
            rm -rf "$TMPDIR"
            exit 1
          fi
        elif command -v shasum >/dev/null 2>&1; then
          if (cd "$TMPDIR" && shasum -a 256 -c install.sh.sha256 >/dev/null 2>&1); then
            info "Installer checksum verified."
          else
            warn "Installer checksum mismatch! Aborting."
            rm -rf "$TMPDIR"
            exit 1
          fi
        else
          warn "No sha256 tool found; skipping checksum verification."
        fi
      else
        warn "Could not fetch installer checksum; skipping verification."
      fi
    fi
    rm -rf "$TMPDIR"
  fi
fi

OS="$(uname -s 2>/dev/null || echo unknown)"

case "$OS" in
  Linux|Darwin) ;;
  *)
    warn "This curl installer supports macOS and Linux only."
    warn "On Windows, install Python from https://www.python.org, then run:"
    warn '    pip install "backstop-ai[anthropic]"'
    exit 1
    ;;
esac

if ! command -v python3 >/dev/null 2>&1; then
  warn "Python 3 was not found on this machine."
  if [ "$OS" = "Darwin" ]; then
    warn "Install it with:  brew install python"
  else
    warn "Install it with:  sudo apt install python3 python3-pip"
  fi
  warn "Or download it from https://www.python.org"
  exit 1
fi

if ! python3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)"; then
  PYVER="$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
  warn "Backstop needs Python >= 3.10 (found $PYVER)."
  exit 1
fi

info "Using $(command -v python3) ($(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])'))"

# Make sure pip itself is available.
if ! python3 -m pip --version >/dev/null 2>&1; then
  info "Bootstrapping pip via ensurepip..."
  if ! python3 -m ensurepip --user >/dev/null 2>&1; then
    warn "Could not bootstrap pip automatically."
    warn "Please install pip, then re-run this installer."
    exit 1
  fi
fi

EXTRAS="${BACKSTOP_EXTRAS:-anthropic}"
BACKSTOP_VERSION="0.8.0"
SPEC="backstop-ai[$EXTRAS]==${BACKSTOP_VERSION}"

# Is this Python one of the "externally managed" ones — Debian, Ubuntu 23.04+,
# Fedora? There, `pip install --user` is refused with
# `error: externally-managed-environment`, and it was refused for every user
# of this script on those systems. The answer is a virtualenv, not
# `--break-system-packages`: a guardrail that breaks the system's Python to
# install itself is a bad guardrail.
EXTERNALLY_MANAGED=0
if python3 -c "import sysconfig, os, sys; p = sysconfig.get_path('stdlib') or ''; sys.exit(0 if os.path.exists(os.path.join(p, 'EXTERNALLY-MANAGED')) else 1)" 2>/dev/null; then
  EXTERNALLY_MANAGED=1
fi

PIP_ARGS="--user --upgrade"
VENV_DIR="${BACKSTOP_VENV:-$HOME/.local/share/backstop-venv}"
PIP_BIN="python3 -m pip"

if [ "$EXTERNALLY_MANAGED" = "1" ]; then
  info "This Python is externally managed, so installing into it is refused."
  info "Using a virtualenv at $VENV_DIR instead."
  if [ ! -d "$VENV_DIR" ]; then
    python3 -m venv "$VENV_DIR" || {
      warn "Could not create a virtualenv at $VENV_DIR."
      warn "Install it yourself with:  python3 -m venv $VENV_DIR"
      warn "then:  $VENV_DIR/bin/pip install '$SPEC'"
      exit 1
    }
  fi
  PIP_ARGS=""
  PIP_BIN="$VENV_DIR/bin/pip"
fi

info "Installing $SPEC..."
if $PIP_BIN install $PIP_ARGS "$SPEC"; then
  :
elif [ "${BACKSTOP_NO_GITFALLBACK:-0}" = "1" ]; then
  warn "Install failed. See output above."
  exit 1
else
  warn "PyPI install failed; falling back to the GitHub repository."
  warn "The fallback installs current source, not a pinned or verified release."
  $PIP_BIN install $PIP_ARGS "backstop-ai[$EXTRAS] @ git+https://github.com/RavaniRoshan/backstop.git"
fi

info "Backstop installed."

if [ "$EXTERNALLY_MANAGED" = "1" ]; then
  cat <<EOF

   Backstop is in the virtualenv at $VENV_DIR.

   Try:   $VENV_DIR/bin/backstop --help
          $VENV_DIR/bin/wedge --help

   To use it without the full path, add this to your shell profile:
          export PATH="$VENV_DIR/bin:\$PATH"
EOF
  exit 0
fi

USER_BIN="$(python3 -m site --user-base)/bin"
cat <<EOF

   Try:   backstop --help
          wedge --help

   If 'backstop' is not on your PATH, add this to your shell profile:
          export PATH="$USER_BIN:\$PATH"
EOF
