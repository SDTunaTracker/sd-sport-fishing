"""Tests for scripts/build-prod.py — production HTML patcher.

Focus: --meta-only mode (added 2026-09-07 so Cloudflare Pages can stamp
build-commit/build-time on every deploy without also blanket-rewriting
every ?v= tag to the deploy sha).
"""
from __future__ import annotations
import importlib.util
import os
import sys
from pathlib import Path

import pytest

# `scripts/build-prod.py` has a dash in its name, so import via importlib.
_HERE = Path(__file__).resolve().parent
_SCRIPT = _HERE.parent / "scripts" / "build-prod.py"
_spec = importlib.util.spec_from_file_location("build_prod", _SCRIPT)
build_prod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(build_prod)


# -----------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------

RAW_INDEX = '''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="build-time" content="2026-01-01T00:00:00Z">
<meta name="build-commit" content="deadbee">
<title>The Tuna Tracker</title>
<link rel="stylesheet" href="styles.css?v=20260817-1">
<script src="dates.js?v=20260817-1"></script>
<script src="data.js?v=20260819-2"></script>
<script src="dist/app.js?v=20260817-1"></script>
</head>
<body></body>
</html>
'''


# -----------------------------------------------------------------------
# patch_html — meta-only mode
# -----------------------------------------------------------------------

def test_meta_only_injects_meta_tags():
    out = build_prod.patch_html(
        RAW_INDEX,
        version="ignored-in-meta-only",
        build_sha="abc1234deadbeef",
        build_time="2026-09-07T12:00:00Z",
        meta_only=True,
    )
    assert '<meta name="build-time" content="2026-09-07T12:00:00Z">' in out
    assert '<meta name="build-commit" content="abc1234">' in out


def test_meta_only_leaves_v_tags_alone():
    """The whole point of --meta-only: don't rewrite bundle cache-bust tags."""
    out = build_prod.patch_html(
        RAW_INDEX,
        version="wrong-value-should-not-appear",
        build_sha="abc1234",
        build_time="2026-09-07T12:00:00Z",
        meta_only=True,
    )
    # Original ?v= stamps are preserved verbatim
    assert 'styles.css?v=20260817-1' in out
    assert 'dates.js?v=20260817-1' in out
    assert 'data.js?v=20260819-2' in out
    assert 'dist/app.js?v=20260817-1' in out
    # The passed `version` did NOT get stamped anywhere
    assert 'wrong-value-should-not-appear' not in out


def test_meta_only_replaces_prior_meta_tags():
    """Re-runs don't stack duplicate meta tags."""
    out = build_prod.patch_html(
        RAW_INDEX,
        version="x",
        build_sha="fedcba9",
        build_time="2026-09-07T12:00:00Z",
        meta_only=True,
    )
    # Old (baked-in) values gone
    assert 'content="2026-01-01T00:00:00Z"' not in out
    assert 'content="deadbee"' not in out
    # Only ONE occurrence of each new meta tag
    assert out.count('<meta name="build-time"') == 1
    assert out.count('<meta name="build-commit"') == 1


def test_meta_only_leaves_babel_and_jsx_refs_alone():
    """--meta-only skips Babel removal and JSX-ref rewriting."""
    html = RAW_INDEX.replace(
        '<script src="dist/app.js?v=20260817-1"></script>',
        (
            '<script type="text/babel" src="app.jsx?v=20260817-1"></script>\n'
            '<script src="//cdn.jsdelivr.net/npm/@babel/standalone/babel.min.js"></script>'
        ),
    )
    out = build_prod.patch_html(
        html, version="x", build_sha="abc1234",
        build_time="2026-09-07T12:00:00Z", meta_only=True,
    )
    assert 'type="text/babel"' in out          # NOT rewritten
    assert 'babel.min.js' in out                # NOT removed
    assert 'app.jsx?v=20260817-1' in out        # NOT rewritten to dist/


# -----------------------------------------------------------------------
# Loud-failure guarantees
# -----------------------------------------------------------------------

def test_missing_anchor_raises_loudly():
    """A silent no-op on the anchor defeats the purpose — must exit nonzero."""
    html_no_anchor = RAW_INDEX.replace('<meta charset="utf-8">', '<!-- no anchor -->')
    with pytest.raises(ValueError, match="anchor"):
        build_prod.patch_html(
            html_no_anchor, version="x", build_sha="abc1234",
            build_time="2026-09-07T12:00:00Z", meta_only=True,
        )


def test_meta_only_without_sha_exits_nonzero(tmp_path, monkeypatch):
    """CLI path: --meta-only with no sha available anywhere is fatal."""
    # Isolate: point index.html at a temp copy, clear the env vars.
    web_dir = tmp_path / "web"
    web_dir.mkdir()
    (web_dir / "index.html").write_text(RAW_INDEX, encoding="utf-8")
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    monkeypatch.setattr(
        build_prod.os.path, "abspath",
        lambda _p: str(scripts_dir / "build-prod.py"),
    )
    monkeypatch.delenv("GITHUB_SHA", raising=False)
    monkeypatch.delenv("CF_PAGES_COMMIT_SHA", raising=False)
    rc = build_prod.main(["--meta-only"])
    assert rc == 2


def test_meta_only_cli_from_positional_sha(tmp_path, monkeypatch, capsys):
    """--meta-only with a positional sha and no env vars still works."""
    web_dir = tmp_path / "web"
    web_dir.mkdir()
    (web_dir / "index.html").write_text(RAW_INDEX, encoding="utf-8")
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    monkeypatch.setattr(
        build_prod.os.path, "abspath",
        lambda _p: str(scripts_dir / "build-prod.py"),
    )
    monkeypatch.delenv("GITHUB_SHA", raising=False)
    monkeypatch.delenv("CF_PAGES_COMMIT_SHA", raising=False)
    rc = build_prod.main(["--meta-only", "abc1234deadbeef"])
    assert rc == 0
    result = (web_dir / "index.html").read_text(encoding="utf-8")
    assert '<meta name="build-commit" content="abc1234">' in result
    # ?v= untouched
    assert 'styles.css?v=20260817-1' in result


# -----------------------------------------------------------------------
# Full mode still works (regression: don't break the historical path)
# -----------------------------------------------------------------------

def test_full_mode_stamps_all_v_tags_with_version():
    out = build_prod.patch_html(
        RAW_INDEX,
        version="20260907-1",
        build_sha="abc1234",
        build_time="2026-09-07T12:00:00Z",
        meta_only=False,
    )
    assert 'styles.css?v=20260907-1' in out
    assert 'dates.js?v=20260907-1' in out
    assert 'dist/app.js?v=20260907-1' in out
    # Meta tags also injected
    assert '<meta name="build-commit" content="abc1234">' in out


def test_full_mode_data_js_override():
    """Step 4: data.js gets its content hash, overriding the VERSION stamp."""
    out = build_prod.patch_html(
        RAW_INDEX,
        version="20260907-1",
        build_sha="abc1234",
        build_time="2026-09-07T12:00:00Z",
        meta_only=False,
        data_js_hash="cafebabe",
    )
    # Every OTHER file uses VERSION
    assert 'styles.css?v=20260907-1' in out
    # data.js uses its content hash
    assert 'data.js?v=cafebabe' in out
    assert 'data.js?v=20260907-1' not in out


def test_full_mode_removes_babel_and_rewrites_jsx():
    html = RAW_INDEX.replace(
        '<script src="dist/app.js?v=20260817-1"></script>',
        (
            '<script type="text/babel" src="app.jsx?v=20260817-1"></script>\n'
            '<script src="//cdn.jsdelivr.net/npm/@babel/standalone/babel.min.js"></script>'
        ),
    )
    out = build_prod.patch_html(
        html, version="20260907-1", build_sha="abc1234",
        build_time="2026-09-07T12:00:00Z", meta_only=False,
    )
    assert 'babel.min.js' not in out
    assert 'type="text/babel"' not in out
    assert 'src="dist/app.js?v=20260907-1"' in out


def test_full_mode_no_sha_still_stamps_v_but_skips_meta():
    """Legacy: if no sha (local dev run), stamp ?v= but don't inject meta."""
    out = build_prod.patch_html(
        RAW_INDEX,
        version="20260907-1",
        build_sha=None,
        build_time="2026-09-07T12:00:00Z",
        meta_only=False,
    )
    assert 'styles.css?v=20260907-1' in out
    # No sha means no meta injection — old (baked-in) tags stripped;
    # nothing new stamped.
    assert '<meta name="build-time"' not in out
    assert '<meta name="build-commit"' not in out
