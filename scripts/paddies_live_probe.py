"""
Diagnostic live-run: extract mentions from the 5 most-recent unextracted
paddy_sources rows. Reports raw Claude JSON, validated mentions, unresolved
counts, and per-call token usage. WRITES to tracker.db (paddy_mentions +
flips extracted=1). Ordinary CLI use should be `python -m scraper.paddies.extract`.
"""
from __future__ import annotations
import json
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Load .env
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass

import anthropic

from scraper.paddies import extract as ex

DB = ROOT / "tracker.db"
N_POSTS = 5

def main():
    gaz = ex.load_gazetteer()
    client = anthropic.Anthropic()  # picks up ANTHROPIC_API_KEY from env

    conn = sqlite3.connect(DB, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 30000")
    ex.ensure_schema(conn)

    rows = list(conn.execute(
        "SELECT id, url, title, author, published_at, raw_text "
        "FROM paddy_sources WHERE extracted = 0 "
        "ORDER BY published_at DESC LIMIT ?", (N_POSTS,)
    ))
    print(f"processing {len(rows)} posts\n")

    total_in = total_out = 0
    for i, row in enumerate(rows, 1):
        print(f"=== [{i}/{len(rows)}] id={row['id'][:10]}  {row['title']!r} ===")
        print(f"    url={row['url']}")
        print(f"    published={row['published_at']}  author={row['author']}  body_len={len(row['raw_text'])}")

        prompt = ex.build_prompt(row["title"], row["published_at"],
                                 row["raw_text"], gaz["prompt_lines"])
        t0 = time.monotonic()
        try:
            resp = client.messages.create(
                model=ex.MODEL,
                max_tokens=ex.MAX_TOKENS,
                messages=[{"role": "user", "content": prompt}],
            )
        except Exception as e:
            print(f"    !! API error: {e!r}\n")
            continue
        dt = time.monotonic() - t0

        in_tok = resp.usage.input_tokens
        out_tok = resp.usage.output_tokens
        total_in += in_tok
        total_out += out_tok
        text = resp.content[0].text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            end = len(lines) - 1 if lines[-1].strip() == "```" else len(lines)
            text = "\n".join(lines[1:end]).strip()

        print(f"    tokens: input={in_tok}  output={out_tok}  latency={dt:.2f}s")
        print(f"    --- raw Claude JSON ---")
        # Reformat for readability if it's valid JSON; else print as-is
        try:
            parsed = json.loads(text)
            print("    " + json.dumps(parsed, indent=2).replace("\n", "\n    "))
        except json.JSONDecodeError as e:
            print(f"    (JSON parse error: {e})")
            print(f"    {text[:2000]}")
            continue

        # Validate + write
        cleaned = []
        unresolved = 0
        for m in parsed:
            v = ex.validate_mention(m, gaz["valid_ids"], row["id"])
            if v is None:
                continue
            if v["bank"] is None and not json.loads(v["route_json"]):
                unresolved += 1
            cleaned.append(v)
        ex.replace_mentions(
            conn, row["id"], cleaned,
            datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00"),
        )
        conn.commit()

        print(f"    --- validated ---")
        print(f"    mentions_written={len(cleaned)}  unresolved={unresolved}")
        for k, v in enumerate(cleaned):
            print(f"      [{k}] bank={v['bank']!r}  route={v['route_json']}  "
                  f"paddy_count={v['paddy_count']}  holding={v['holding']}  "
                  f"species={v['species_json']}  confidence={v['confidence']}")
            print(f"          quote={v['quote']!r}")
        print()
        time.sleep(0.5)

    print(f"totals: input_tokens={total_in}  output_tokens={total_out}")
    conn.close()

if __name__ == "__main__":
    main()
