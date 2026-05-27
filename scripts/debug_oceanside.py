"""Fetch the Oceanside page and show first 2000 chars of raw HTML."""
import sys, requests
sys.path.insert(0, '.')
from src.scrape import UA

url = "https://www.fishcounts.com/oceanside/fishcounts.php"
r = requests.get(url, headers={"User-Agent": UA, "Accept": "text/html"}, timeout=30)
print(f"Status: {r.status_code}  Length: {len(r.text):,}")
# Show a chunk around the first table element
idx = r.text.lower().find('<table')
if idx >= 0:
    print("--- table found ---")
    print(r.text[idx:idx+1500])
else:
    print("No <table> found. First 1500 chars:")
    print(r.text[:1500])
