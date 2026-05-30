"""
Peek at the AIS discovery run without disrupting it.

Usage:
    .venv/Scripts/python.exe scripts/check-discover-progress.py
"""

import json
from datetime import datetime
from pathlib import Path

ROOT    = Path(__file__).parent.parent
LOG_DIR = ROOT / 'logs'

def check_progress():
    pid_file = LOG_DIR / 'ais-discover.pid'
    if not pid_file.exists():
        print("No active discovery run found (logs/ais-discover.pid missing).")
        return

    pid = int(pid_file.read_text().strip())

    try:
        import psutil
        try:
            proc = psutil.Process(pid)
            running = proc.is_running() and proc.status() != psutil.STATUS_ZOMBIE
            runtime_s = datetime.now().timestamp() - proc.create_time()
            hours     = runtime_s / 3600
            print(f"Process : {'RUNNING' if running else 'STOPPED'}")
            print(f"PID     : {pid}")
            print(f"Runtime : {hours:.1f} h")
            print(f"Remaining: {max(0, 8 - hours):.1f} h")
        except psutil.NoSuchProcess:
            print(f"Process {pid} is no longer running (run may have finished).")
    except ImportError:
        print(f"PID: {pid}  (install psutil for runtime info)")

    # Check latest log file
    logs = sorted(LOG_DIR.glob('ais-discover-*.log'))
    if logs:
        log = logs[-1]
        lines = log.read_text(encoding='utf-8', errors='replace').splitlines()
        match_lines = [l for l in lines if 'MATCH' in l]
        error_lines = [l for l in lines if 'error' in l.lower() or 'ERROR' in l]
        print(f"\nLog     : {log.name}")
        print(f"Lines   : {len(lines)}")
        print(f"Matches : {len(match_lines)}")
        if error_lines:
            print(f"Errors  : {len(error_lines)} (last: {error_lines[-1][:80]})")
        if match_lines:
            print("\nLatest matches from log:")
            for l in match_lines[-5:]:
                print(f"  {l.strip()}")

    # Check vessel_mmsi.json output file
    out = ROOT / 'data' / 'vessel_mmsi.json'
    if out.exists():
        data    = json.loads(out.read_text(encoding='utf-8'))
        vessels = data.get('vessels', {})
        print(f"\nMMSIs in vessel_mmsi.json : {len(vessels)}")
        print(f"Last discovery run        : {data.get('_last_discover_run', 'unknown')}")
        if vessels:
            print("\nAll mapped vessels:")
            for mmsi, info in sorted(vessels.items(), key=lambda x: x[1].get('name', '')):
                print(f"  {mmsi}  {info.get('name','?'):30s}  {info.get('landing','')}")
    else:
        print("\ndata/vessel_mmsi.json not found yet.")

    print()
    print("To stop the run:  Stop-Process -Id", pid, " (PowerShell)")
    print("                  kill", pid, "           (bash)")

if __name__ == '__main__':
    check_progress()
