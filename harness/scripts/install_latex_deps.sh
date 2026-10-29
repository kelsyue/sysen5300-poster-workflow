#!/usr/bin/env bash
# Install every TeX Live package src/latex_poster.py needs (TinyTeX or TeX Live, no sudo
# for TinyTeX). The list is every package the P01 build loaded (from its .fls recorder
# file), plus the xetex engine and latexmk. tlmgr skips packages already installed.
#
# Usage (from harness/):  bash scripts/install_latex_deps.sh
set -euo pipefail

PKGS="xetex latexmk
amscls amsfonts amsmath anyfontsize atbegshi beamer beamerposter bigintcalc bitset
booktabs changepage cm etoolbox fontspec fp geometry gettitlestring graphics graphics-cfg
graphics-def hycolor hyperref iftex infwarerr intcalc kpathsea kvdefinekeys kvoptions
kvsetkeys l3backend l3kernel l3packages latex lm ltxcmds natbib pdfescape pdftexcmds pgf
pgfplots ragged2e refcount rerunfilecheck stringenc tools translator type1cm uniquecounter
url xcolor xkeyval zapfding"

# A TeX Live older than the current release can't install from the normal mirrors
# ("Local TeX Live (2025) is older than remote repository (2026)"); fall back to the
# frozen archive for the installed year.
# shellcheck disable=SC2086
if ! tlmgr install $PKGS; then
  year=$(tlmgr --version | sed -n 's/.*TeX Live.* version \([0-9]\{4\}\).*/\1/p' | head -1)
  echo "Retrying from the frozen TeX Live $year archive"
  tlmgr --repository "https://ftp.math.utah.edu/pub/tex/historic/systems/texlive/$year/tlnet-final" install $PKGS
fi
