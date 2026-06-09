#!/usr/bin/env bash
# Guard against prefix-less client-side URLs.
#
# The app is served behind a reverse proxy under a deployment prefix
# (e.g. /explore). Every internal URL built in the browser must carry that
# prefix or it 404s in production. The convention:
#
#   Jinja templates : {{ base }}/...   or   base + '/...'
#   JavaScript      : cgUrl('/...')    (cgUrl is defined in base.html)
#                     window.SCRIPT_ROOT is also acceptable in bundled JS
#
# This script fails if it finds a client URL built from a bare leading-slash
# literal (fetch / .href / location assignment) that bypasses those helpers.

set -euo pipefail
cd "$(dirname "$0")/.."

# Dangerous: fetch / href / location assignment with a bare "/..." literal.
PATTERN='(fetch\(|\.href[[:space:]]*=|location\.href[[:space:]]*=|window\.location[[:space:]]*=)[[:space:]]*[`'"'"'"]/'

# Approved helpers that make a leading-slash literal safe on the same line.
ALLOW='cgUrl|SCRIPT_ROOT|\{\{ ?base ?\}\}'

hits=$(grep -rnE "$PATTERN" flask_templates/ vite/src/ 2>/dev/null \
        | grep -vE "$ALLOW" || true)

if [ -n "$hits" ]; then
    echo "ERROR: prefix-less client URL(s) found. Use cgUrl()/{{ base }}:" >&2
    echo "$hits" >&2
    exit 1
fi

echo "URL lint passed: no prefix-less client URLs found."
