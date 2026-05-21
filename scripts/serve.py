"""Local launcher: opens the dashboard in the default browser and serves web/.

Designed so the desktop shortcut can point straight at python.exe + this file,
avoiding PowerShell/CMD entirely (those tend to be blocked by corporate policy).
"""
from __future__ import annotations

import http.server
import os
import socketserver
import sys
import threading
import time
import webbrowser
from pathlib import Path

PORT = 8765
URL = f"http://localhost:{PORT}/SD%20Sport%20Fishing.html"


def main() -> int:
    web_dir = Path(__file__).resolve().parents[1] / "web"
    if not web_dir.is_dir():
        print(f"web/ not found at {web_dir}", file=sys.stderr)
        return 1
    os.chdir(web_dir)

    def open_browser() -> None:
        time.sleep(0.5)
        webbrowser.open(URL)

    threading.Thread(target=open_browser, daemon=True).start()

    print(f"Serving {web_dir}")
    print(f"  -> {URL}")
    print("Close this window (or press Ctrl-C) to stop the server.")
    with socketserver.TCPServer(("127.0.0.1", PORT), http.server.SimpleHTTPRequestHandler) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
