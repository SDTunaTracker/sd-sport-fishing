#!/usr/bin/env python3
"""
Production build helper: patches web/index.html for the esbuild-compiled output.

Called by the Cloudflare Pages build command as:
    python3 scripts/build-prod.py $CF_PAGES_COMMIT_SHA               # full patch
    python3 scripts/build-prod.py --meta-only $CF_PAGES_COMMIT_SHA   # meta only

Modes:

  full (default): applies all patches
    1. Remove the @babel/standalone CDN script (esbuild pre-compiles JSX instead)
    2. Replace type="text/babel" src="name.jsx?v=..." with src="dist/name.js?v=VERSION"
    3. Stamp all remaining ?v= query strings with VERSION
    4. Stamp data.js ?v= with its MD5 content hash (overrides step 3 for data.js only)
    5. Inject build-time and build-commit meta tags

  --meta-only: applies ONLY step 5
    - Leaves ?v= tags untouched (avoids busting every bundle's browser cache
      on every deploy just because the sha changed)
    - Still fails loudly if the anchor `<meta charset="utf-8">` is absent or if
      no build sha is available — a silent no-op would defeat the purpose.

Exit codes:
  0  patched successfully (or no-op that was expected)
  2  anchor not found in index.html, or --meta-only requested without a sha
"""
import argparse
import hashlib
import os
import pathlib
import re
import sys
from datetime import datetime, timezone

ANCHOR = '<meta charset="utf-8">'


def patch_html(
    text: str,
    *,
    version: str,
    build_sha: str | None,
    build_time: str,
    meta_only: bool,
    data_js_hash: str | None = None,
) -> str:
    """
    Apply the requested patches to `text` and return the new HTML. Raises
    ValueError if the anchor is missing or if a required patch produced a
    silent no-op.
    """
    if ANCHOR not in text:
        raise ValueError(
            f"anchor {ANCHOR!r} not found in web/index.html — cannot "
            "inject build-time/build-commit meta tags"
        )

    if not meta_only:
        # 1. Drop the Babel CDN <script>
        text = re.sub(
            r"\n?[ \t]*<script[^>]+babel\.min\.js[^>]*></script>", "", text
        )
        # 2. Rewrite type="text/babel" JSX refs -> compiled dist/ refs
        text = re.sub(
            r'type="text/babel" src="([^"]+)\.jsx\?v=[^"]+"',
            lambda m: f'src="dist/{m.group(1)}.js?v={version}"',
            text,
        )
        # 3. Stamp all remaining ?v= with VERSION
        text = re.sub(r"\?v=[^\"'\s]+", f"?v={version}", text)
        # 4. Override data.js ?v= with its content hash
        if data_js_hash is not None:
            text = re.sub(
                r'src="data\.js(\?v=[^"]*)?"',
                f'src="data.js?v={data_js_hash}"',
                text,
            )

    # 5. Meta injection (always runs; that's the point of --meta-only)
    # Strip any previously-injected build tags so re-runs never stack duplicates.
    text = re.sub(r'\n?<meta name="build-(?:time|commit)"[^>]*>', '', text)
    if build_sha:
        meta_tags = (
            f'\n<meta name="build-time" content="{build_time}">'
            f'\n<meta name="build-commit" content="{build_sha[:7]}">'
        )
        text = text.replace(ANCHOR, f"{ANCHOR}{meta_tags}", 1)

    # Assertions — turn silent no-ops into loud failures
    if not meta_only:
        if "babel.min.js" in text:
            raise ValueError("Babel script tag not removed")
        if 'type="text/babel"' in text:
            raise ValueError('type="text/babel" still present')
        if f"?v={version}" not in text:
            raise ValueError(f"version string ?v={version} not stamped anywhere")
    if build_sha:
        if f'content="{build_time}"' not in text:
            raise ValueError("build-time meta not injected")
        if f'content="{build_sha[:7]}"' not in text:
            raise ValueError("build-commit meta not injected")

    return text


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Patch web/index.html for production deploy.",
    )
    parser.add_argument(
        "version",
        nargs="?",
        default=None,
        help="Value to stamp into ?v=… (also treated as the build sha if the "
             "GITHUB_SHA / CF_PAGES_COMMIT_SHA env vars aren't set).",
    )
    parser.add_argument(
        "--meta-only",
        action="store_true",
        help="Only inject build-time/build-commit meta tags. Skip Babel "
             "removal, JSX-ref rewrites, and ?v= stamping.",
    )
    args = parser.parse_args(argv)

    build_sha = (
        os.environ.get("GITHUB_SHA")
        or os.environ.get("CF_PAGES_COMMIT_SHA")
        or args.version
    )
    version = args.version or (build_sha[:7] if build_sha else "prod")
    build_time = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    if args.meta_only and not build_sha:
        print(
            "FATAL: --meta-only requires a build sha "
            "(GITHUB_SHA, CF_PAGES_COMMIT_SHA, or positional argument)",
            file=sys.stderr,
        )
        return 2

    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.normpath(os.path.join(here, "..", "web", "index.html"))
    data_js_path = pathlib.Path(os.path.normpath(
        os.path.join(here, "..", "web", "data.js")))
    print(f"Patching: {path}  (mode={'meta-only' if args.meta_only else 'full'})")

    text = open(path, encoding="utf-8").read()

    data_js_hash = None
    if not args.meta_only and data_js_path.exists():
        data_js_hash = hashlib.md5(data_js_path.read_bytes()).hexdigest()[:8]
        print(f"data.js hash: {data_js_hash}")

    try:
        text = patch_html(
            text,
            version=version,
            build_sha=build_sha,
            build_time=build_time,
            meta_only=args.meta_only,
            data_js_hash=data_js_hash,
        )
    except ValueError as e:
        print(f"FATAL: {e}", file=sys.stderr)
        return 2

    open(path, "w", encoding="utf-8").write(text)

    sha_disp = build_sha[:7] if build_sha else "none"
    print(
        f"OK: patched web/index.html "
        f"(mode={'meta-only' if args.meta_only else 'full'}, "
        f"version={version}, commit={sha_disp}, time={build_time})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
