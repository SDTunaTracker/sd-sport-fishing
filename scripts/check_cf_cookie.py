"""Check if we have a valid cf_clearance cookie for 976-tuna.com in Chrome."""
import sqlite3, shutil, os, tempfile, sys, requests

src = r'C:\Users\Jenelle\AppData\Local\Google\Chrome\User Data\Default\Network\Cookies'
tmp = os.path.join(tempfile.gettempdir(), 'chrome_cookies_copy.db')
shutil.copy2(src, tmp)

conn = sqlite3.connect(tmp)
rows = conn.execute(
    "SELECT host_key, name, value, expires_utc FROM cookies "
    "WHERE host_key LIKE '%976-tuna%' ORDER BY expires_utc DESC"
).fetchall()
conn.close()

print(f"Found {len(rows)} 976-tuna.com cookies:")
for r in rows:
    print(f"  {r[0]}  {r[1]}  value_len={len(r[2])}  expires={r[3]}")

cf = next((r for r in rows if r[1] == 'cf_clearance'), None)
if not cf:
    print("\nNo cf_clearance cookie found - user needs to visit 976-tuna.com in Chrome first.")
    sys.exit(1)

# Try using it in a requests call
print(f"\ncf_clearance found! Testing against 976-tuna.com...")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36")
session = requests.Session()
session.cookies.set('cf_clearance', cf[2], domain='.976-tuna.com')
r = session.get(
    'https://www.976-tuna.com/landing/7/dana-wharf/counts?m=8&y=2025',
    headers={'User-Agent': UA, 'Accept': 'text/html'},
    timeout=20
)
print(f"Status: {r.status_code}  len: {len(r.text)}")
print(f"Security check: {'Security Check' in r.text or 'cf-turnstile' in r.text}")
print(f"Has h2: {'<h2' in r.text}")
