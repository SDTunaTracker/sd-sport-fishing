#!/usr/bin/env python3
"""
Production build helper: patches web/index.html for the esbuild-compiled output.

Called by .github/workflows/deploy-pages.yml as:
    python3 scripts/build-prod.py <VERSION>

What it does:
  1. Removes the @babel/standalone CDN script (esbuild pre-compiles JSX instead)
  2. Replaces type="text/babel" src="name.jsx?v=..." with src="dist/name.js?v=VERSION"
  3. Stamps all remaining ?v= query strings with VERSION
"""
import re, sys, os

version = sys.argv[1] if len(sys.argv) > 1 else "prod"
root    = os.path.join(os.path.dirname(__file__), "..")
path    = os.path.join(root, "web", "index.html")

text = open(path, encoding="utf-8").read()

# Remove @babel/standalone script tag (one line)
text = re.sub(r"\n?[ \t]*<script[^>]+babel\.min\.js[^>]*></script>", "", text)

# Replace type="text/babel" JSX refs → compiled dist/ refs
text = re.sub(
    r'type="text/babel" src="([^"]+)\.jsx\?v=[^"]+"',
    lambda m: f'src="dist/{m.group(1)}.js?v={version}"',
    text,
)

# Stamp all remaining ?v= query strings (CSS, plain JS) with VERSION
text = re.sub(r"\?v=[^\"'\s]+", f"?v={version}", text)

open(path, "w", encoding="utf-8").write(text)
print(f"Patched web/index.html for production (version={version})")
