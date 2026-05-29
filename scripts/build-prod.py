#!/usr/bin/env python3
"""
Production build helper: patches web/index.html for the esbuild-compiled output.

Called by .github/workflows/deploy-pages.yml as:
    python3 scripts/build-prod.py <VERSION>

What it does:
  1. Removes the @babel/standalone CDN script (esbuild pre-compiles JSX instead)
  2. Replaces type="text/babel" src="name.jsx?v=..." with src="dist/name.js?v=VERSION"
  3. Stamps all remaining ?v= query strings with VERSION
  4. Injects build-time and build-commit meta tags
"""
import re, sys, os
from datetime import datetime, timezone

version    = sys.argv[1] if len(sys.argv) > 1 else "prod"
build_time = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
build_sha  = os.environ.get("GITHUB_SHA", "local")[:7]

# Use abspath(__file__) so this works regardless of how/where the script is invoked.
here = os.path.dirname(os.path.abspath(__file__))
path = os.path.normpath(os.path.join(here, "..", "web", "index.html"))
print(f"Patching: {path}")

text = open(path, encoding="utf-8").read()

# 1. Remove @babel/standalone script tag (one line)
text = re.sub(r"\n?[ \t]*<script[^>]+babel\.min\.js[^>]*></script>", "", text)

# 2. Replace type="text/babel" JSX refs → compiled dist/ refs
text = re.sub(
    r'type="text/babel" src="([^"]+)\.jsx\?v=[^"]+"',
    lambda m: f'src="dist/{m.group(1)}.js?v={version}"',
    text,
)

# 3. Stamp all remaining ?v= query strings (CSS, plain JS) with VERSION
text = re.sub(r"\?v=[^\"'\s]+", f"?v={version}", text)

# 4. Inject build metadata meta tags after <meta charset="utf-8">
meta_tags = (
    f'\n<meta name="build-time" content="{build_time}">'
    f'\n<meta name="build-commit" content="{build_sha}">'
)
text = text.replace('<meta charset="utf-8">', f'<meta charset="utf-8">{meta_tags}', 1)

open(path, "w", encoding="utf-8").write(text)

# Assertions — exit non-zero if any patch step was a no-op
assert "babel.min.js" not in text, "PATCH FAILED: Babel script tag not removed"
assert 'type="text/babel"' not in text, "PATCH FAILED: type=text/babel still present"
assert f"?v={version}" in text, "PATCH FAILED: version string not stamped"
assert f'content="{build_time}"' in text, "PATCH FAILED: build-time meta not injected"
assert f'content="{build_sha}"' in text, "PATCH FAILED: build-commit meta not injected"

print(f"OK: patched web/index.html (version={version}, commit={build_sha}, time={build_time})")
