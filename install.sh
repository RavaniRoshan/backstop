#!/bin/sh
# Backstop — one-command installer (convenience / secondary path).
#
# Canonical install remains:   pip install "backstop[anthropic]"
# This script is for users who don't have pip/Python knowledge: it detects
# Python and runs the pip install for you.
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
set -eu

BOLD=''
NORM=''
if [ -t 1 ]; then BOLD='\033[1m'; NORM='\033[0m'; fi
info() { printf "${BOLD}==>${NORM} %s\n" "$1"; }
warn() { printf "!! %s\n" "$1" >&2; }

OS="$(uname -s 2>/dev/null || echo unknown)"

case "$OS" in
  Linux|Darwin) ;;
  *)
    warn "This curl installer supports macOS and Linux only."
    warn "On Windows, install Python from https://www.python.org, then run:"
    warn '    pip install "backstop[anthropic]"'
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
SPEC="backstop[$EXTRAS]"

info "Installing $SPEC (user scheme)..."
if python3 -m pip install --user --upgrade "$SPEC"; then
  :
elif [ "${BACKSTOP_NO_GITFALLBACK:-0}" = "1" ]; then
  warn "Install failed. See output above."
  exit 1
else
  warn "PyPI install failed; falling back to the GitHub repository."
  warn "(This is expected before Backstop is published to PyPI.)"
  python3 -m pip install --user --upgrade "git+https://github.com/RavaniRoshan/backstop.git#egg=backstop[$EXTRAS]"
fi

info "Backstop installed."
USER_BIN="$(python3 -m site --user-base)/bin"
cat <<EOF

   Try:   backstop --help
          wedge --help

   If 'backstop' is not on your PATH, add this to your shell profile:
          export PATH="$USER_BIN:\$PATH"
EOF
