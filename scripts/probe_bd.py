"""
Phase 0 probe for BD SoCal Offshore forum.
Reports RSS access, sample thread access, and robots.txt / ToS.
Prints a compact report — no side effects.
"""
import re
import sys
import time
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET

UA = "TunaTracker/1.0 (+https://thetunatracker.com)"
BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
TIMEOUT = 10

FORUM = "https://www.bdoutdoors.com/forums/forum/southern-california-offshore-fishing-reports/"
RSS = FORUM + "index.rss"
ROBOTS = "https://www.bdoutdoors.com/robots.txt"
TERMS_CANDIDATES = [
    "https://www.bdoutdoors.com/terms/",
    "https://www.bdoutdoors.com/help/terms/",
    "https://www.bdoutdoors.com/help/terms-and-rules/",
    "https://www.bdoutdoors.com/help/rules/",
]


def fetch(url, ua=BROWSER_UA):
    req = urllib.request.Request(url, headers={
        "User-Agent": ua,
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
    })
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            body = r.read()
            return {
                "ok": True,
                "status": r.status,
                "ctype": r.headers.get("Content-Type", ""),
                "len": len(body),
                "body": body,
                "elapsed_ms": int((time.time() - t0) * 1000),
                "final_url": r.geturl(),
            }
    except urllib.error.HTTPError as e:
        return {
            "ok": False,
            "status": e.code,
            "ctype": e.headers.get("Content-Type", "") if e.headers else "",
            "len": 0,
            "body": (e.read() if hasattr(e, "read") else b"")[:2000],
            "elapsed_ms": int((time.time() - t0) * 1000),
            "err": str(e),
        }
    except Exception as e:
        return {"ok": False, "status": None, "err": repr(e),
                "elapsed_ms": int((time.time() - t0) * 1000)}


def hdr(s):
    print("\n" + "=" * 8 + " " + s + " " + "=" * 8)


def main():
    # (0) robots.txt
    hdr("robots.txt")
    r = fetch(ROBOTS)
    print(f"status={r.get('status')} ctype={r.get('ctype')} bytes={r.get('len')} ms={r.get('elapsed_ms')}")
    if r.get("ok"):
        text = r["body"].decode("utf-8", "replace")
        print("---- robots.txt (verbatim) ----")
        print(text)
        print("---- end robots.txt ----")
    else:
        print("robots.txt fetch failed:", r.get("err"))

    # (a) RSS feed
    hdr("(a) RSS feed")
    r = fetch(RSS)
    print(f"url={RSS}")
    print(f"status={r.get('status')} ctype={r.get('ctype')} bytes={r.get('len')} ms={r.get('elapsed_ms')}")
    sample_thread_url = None
    if r.get("ok") and r["body"]:
        raw = r["body"]
        # try parse as RSS
        try:
            root = ET.fromstring(raw)
            ns = ""
            # find <channel><item>
            items = root.findall(".//item")
            print(f"item_count={len(items)}")
            if items:
                first = items[0]
                title = (first.findtext("title") or "").strip()
                link = (first.findtext("link") or "").strip()
                desc = (first.findtext("description") or "").strip()
                pub = (first.findtext("pubDate") or "").strip()
                # content:encoded if present
                content = None
                for child in first:
                    if child.tag.endswith("encoded"):
                        content = (child.text or "").strip()
                        break
                print(f"first_title={title[:120]!r}")
                print(f"first_link={link}")
                print(f"first_pubDate={pub}")
                print(f"first_description_len={len(desc)}")
                print(f"first_description_head={desc[:400]!r}")
                if content is not None:
                    print(f"first_content_encoded_len={len(content)}")
                    print(f"first_content_encoded_head={content[:400]!r}")
                # collect a sample thread URL
                sample_thread_url = link or None
            else:
                print("no <item> elements found")
                print("head of body:", raw[:500])
        except ET.ParseError as e:
            print("XML parse error:", e)
            print("head of body:", raw[:500])
    else:
        print("RSS fetch failed. head/body:", (r.get("body") or b"")[:500])

    # (b) sample thread
    hdr("(b) sample thread")
    if sample_thread_url:
        # small polite delay
        time.sleep(1.0)
        r2 = fetch(sample_thread_url)
        print(f"url={sample_thread_url}")
        print(f"status={r2.get('status')} ctype={r2.get('ctype')} bytes={r2.get('len')} ms={r2.get('elapsed_ms')}")
        if r2.get("ok"):
            body = r2["body"].decode("utf-8", "replace")
            # crude signals
            lowered = body.lower()
            print("has_cloudflare_challenge:", "just a moment" in lowered or "cf-chl" in lowered or "cf_chl_" in lowered)
            print("has_login_wall:", "you must be logged in" in lowered or "sign up or log in" in lowered)
            # look for first post block (XenForo uses .bbWrapper)
            m = re.search(r'class="bbWrapper"[^>]*>(.{0,2000}?)</div>', body, re.S)
            if m:
                snippet = re.sub(r"<[^>]+>", " ", m.group(1))
                snippet = re.sub(r"\s+", " ", snippet).strip()
                print(f"first_post_snippet_len={len(snippet)}")
                print(f"first_post_snippet_head={snippet[:400]!r}")
            else:
                print("no .bbWrapper block detected (may be blocked or different template)")
        else:
            print("thread fetch failed. head:", (r2.get("body") or b"")[:500])
    else:
        print("no sample thread URL from RSS")

    # (d) ToS pages
    hdr("Terms / rules pages (first that resolves)")
    for url in TERMS_CANDIDATES:
        time.sleep(0.5)
        r3 = fetch(url)
        print(f"try {url} -> status={r3.get('status')} bytes={r3.get('len')}")
        if r3.get("ok") and r3.get("len", 0) > 500:
            text = r3["body"].decode("utf-8", "replace")
            # strip html crudely and pull sentences with keywords
            plain = re.sub(r"<script[\s\S]*?</script>", " ", text, flags=re.I)
            plain = re.sub(r"<style[\s\S]*?</style>", " ", plain, flags=re.I)
            plain = re.sub(r"<[^>]+>", " ", plain)
            plain = re.sub(r"\s+", " ", plain).strip()
            # find clauses mentioning automation / scrape / bot / crawl / api / republish
            keywords = ["scrape", "scraping", "bot", "crawler", "crawl",
                        "automated", "automation", "spider", "harvest",
                        "republish", "reproduce", "commercial", "api"]
            hits = []
            for sent in re.split(r"(?<=[\.!?])\s+", plain):
                low = sent.lower()
                if any(k in low for k in keywords):
                    hits.append(sent.strip())
            print(f"resolved={r3.get('final_url', url)}")
            print(f"clause_hits={len(hits)}")
            for h in hits[:15]:
                print("  •", h[:300])
            break


if __name__ == "__main__":
    main()
