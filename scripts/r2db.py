"""Keep the private data files in a Cloudflare R2 bucket instead of git.

The repo is public, so tracker.db (reviews with ip_hash, scrape logs, host
names), data/paddies.db and data/ais-discoveries.json live in a private R2
bucket. Jobs pull them before running and push them back afterwards; only
public outputs (web/data.js, web/api/v1/*.json, prerendered pages) are
committed.

    python scripts/r2db.py pull tracker.db                 # download, remember ETag
    python scripts/r2db.py push tracker.db                 # upload only if R2 is unchanged
    python scripts/r2db.py status                          # what's in the bucket
    python scripts/r2db.py seed tracker.db ...             # first upload; never overwrites
    python scripts/r2db.py configured                      # exit 0 if R2 secrets are set

Lock: each pull records the object's ETag in .r2-state.json. push sends it
as If-Match, so if anything else wrote the object since our pull, R2 answers
412 and we stop (exit 3) instead of overwriting. A first upload uses
If-None-Match: * so it can't replace an object created meanwhile.

Guards before any upload: SQLite integrity_check, WAL checkpoint, and a
refusal to replace a remote copy with one less than half its size (a fresh
empty DB created by a job that failed to pull). --force skips the size guard.

Every push also writes backups/<name>/<UTC date>.<ext> (one per day, the
day's last push) and prunes backups older than BACKUP_DAYS.

Config (GitHub Actions secrets, or the gitignored .env locally):
    R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET
With none set, every command is a no-op that exits 0 ("not configured"), so
workflows keep using the repo copy until the owner finishes setup.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / ".r2-state.json"
BACKUP_DAYS = 30

# Repo-relative local path -> object key in the bucket.
FILES = {
    "tracker.db": "db/tracker.db",
    "data/paddies.db": "db/paddies.db",
    "data/ais-discoveries.json": "data/ais-discoveries.json",
}

EXIT_CONFLICT = 3
EXIT_GUARD = 4


class Conflict(RuntimeError):
    pass


class Guard(RuntimeError):
    pass


def _env() -> dict[str, str | None]:
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
    except ImportError:
        pass
    g = os.environ.get
    return {k: g(k) for k in ("R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET")}


def configured() -> bool:
    return all(_env().values())


def client():
    import boto3
    from botocore.config import Config
    e = _env()
    return boto3.client(
        "s3",
        endpoint_url=f"https://{e['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com",
        aws_access_key_id=e["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=e["R2_SECRET_ACCESS_KEY"],
        region_name="auto",
        config=Config(retries={"max_attempts": 5, "mode": "standard"}),
    )


def _bucket() -> str:
    return _env()["R2_BUCKET"] or ""


def _load_state(path: Path = STATE) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_state(state: dict, path: Path = STATE) -> None:
    path.write_text(json.dumps(state, indent=1), encoding="utf-8")


def _code(err) -> str:
    return str(getattr(err, "response", {}).get("Error", {}).get("Code", ""))


def _status(err) -> int:
    return int(getattr(err, "response", {}).get("ResponseMetadata", {}).get("HTTPStatusCode", 0) or 0)


def _head(s3, bucket: str, key: str) -> dict | None:
    from botocore.exceptions import ClientError
    try:
        return s3.head_object(Bucket=bucket, Key=key)
    except ClientError as e:
        if _status(e) == 404 or _code(e) in ("404", "NoSuchKey", "NotFound"):
            return None
        raise


def prepare_sqlite(path: Path) -> None:
    """Checkpoint WAL into the main file and verify it before upload."""
    conn = sqlite3.connect(path)
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        ok = conn.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        conn.close()
    if ok != "ok":
        raise Guard(f"{path} failed integrity_check: {ok}")


def pull(name: str, *, s3=None, bucket: str | None = None, root: Path = ROOT,
         state_path: Path = STATE, allow_missing: bool = False) -> str:
    s3 = s3 or client()
    bucket = bucket or _bucket()
    key = FILES[name]
    dest = root / name
    head = _head(s3, bucket, key)
    state = _load_state(state_path)
    if head is None:
        if not allow_missing:
            raise FileNotFoundError(f"r2://{bucket}/{key} does not exist (upload it first)")
        state[name] = None
        _save_state(state, state_path)
        return "missing"
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".r2-download")
    obj = s3.get_object(Bucket=bucket, Key=key, IfMatch=head["ETag"])
    with open(tmp, "wb") as f:
        for chunk in iter(lambda: obj["Body"].read(1 << 20), b""):
            f.write(chunk)
    for suffix in ("-wal", "-shm"):        # stale sidecars from the checkout
        Path(str(dest) + suffix).unlink(missing_ok=True)
    os.replace(tmp, dest)
    state[name] = head["ETag"]
    _save_state(state, state_path)
    return f"{head['ContentLength']} bytes, etag {head['ETag']}"


def push(name: str, *, s3=None, bucket: str | None = None, root: Path = ROOT,
         state_path: Path = STATE, force: bool = False, now: datetime | None = None) -> str:
    from botocore.exceptions import ClientError
    s3 = s3 or client()
    bucket = bucket or _bucket()
    key = FILES[name]
    src = root / name
    if not src.exists():
        raise Guard(f"{src} does not exist")
    if src.suffix == ".db":
        prepare_sqlite(src)
    state = _load_state(state_path)
    if name not in state:
        raise Guard(f"{name} was never pulled in this checkout; pull first so the lock has an ETag")
    expected = state[name]
    head = _head(s3, bucket, key)
    size = src.stat().st_size
    if head is not None and not force and size < 0.5 * head["ContentLength"]:
        raise Guard(f"refusing to replace {head['ContentLength']} bytes with {size} bytes "
                    f"(a fresh or truncated file?); use --force if intended")
    cond = {"IfMatch": expected} if expected else {"IfNoneMatch": "*"}
    try:
        with open(src, "rb") as f:
            res = s3.put_object(Bucket=bucket, Key=key, Body=f, **cond)
    except ClientError as e:
        if _status(e) in (409, 412) or _code(e) in ("PreconditionFailed", "ConditionalRequestConflict"):
            raise Conflict(f"r2://{bucket}/{key} changed since this job pulled it "
                           f"(expected {expected or 'no object'}); not overwriting") from e
        raise
    state[name] = res.get("ETag")
    _save_state(state, state_path)
    _backup(s3, bucket, key, src, now or datetime.now(timezone.utc))
    return f"{size} bytes, etag {res.get('ETag')}"


def _backup(s3, bucket: str, key: str, src: Path, now: datetime) -> None:
    stem, _, ext = key.rpartition(".")
    prefix = f"backups/{key}/"
    with open(src, "rb") as f:
        s3.put_object(Bucket=bucket, Key=f"{prefix}{now:%Y-%m-%d}.{ext}", Body=f)
    cutoff = f"{prefix}{(now - timedelta(days=BACKUP_DAYS)):%Y-%m-%d}"
    resp = s3.list_objects_v2(Bucket=bucket, Prefix=prefix)
    old = [o["Key"] for o in resp.get("Contents", []) if o["Key"] < cutoff]
    for k in old:
        s3.delete_object(Bucket=bucket, Key=k)


def seed(name: str, *, s3=None, bucket: str | None = None, root: Path = ROOT,
         state_path: Path = STATE) -> str:
    """First upload of a local file. Refuses if the object already exists."""
    from botocore.exceptions import ClientError
    s3 = s3 or client()
    bucket = bucket or _bucket()
    src = root / name
    if not src.exists():
        raise Guard(f"{src} does not exist")
    if src.suffix == ".db":
        prepare_sqlite(src)
    try:
        with open(src, "rb") as f:
            res = s3.put_object(Bucket=bucket, Key=FILES[name], Body=f, IfNoneMatch="*")
    except ClientError as e:
        if _status(e) in (409, 412) or _code(e) in ("PreconditionFailed", "ConditionalRequestConflict"):
            raise Conflict(f"r2://{bucket}/{FILES[name]} already exists; not seeding over it") from e
        raise
    state = _load_state(state_path)
    state[name] = res.get("ETag")
    _save_state(state, state_path)
    return f"seeded {src.stat().st_size} bytes, etag {res.get('ETag')}"


def status(*, s3=None, bucket: str | None = None) -> list[str]:
    s3 = s3 or client()
    bucket = bucket or _bucket()
    out = []
    for name, key in FILES.items():
        h = _head(s3, bucket, key)
        out.append(f"{name:28s} " + (f"{h['ContentLength']:>12,} bytes  {h['LastModified']}  {h['ETag']}"
                                      if h else "not in bucket"))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["pull", "push", "seed", "status", "configured"])
    ap.add_argument("names", nargs="*")
    ap.add_argument("--allow-missing", action="store_true", help="pull: not an error if the object is absent")
    ap.add_argument("--force", action="store_true", help="push: skip the size guard (never the lock)")
    a = ap.parse_args(argv)
    if a.cmd == "configured":
        return 0 if configured() else 1
    if not configured():
        print("R2 not configured (R2_ACCOUNT_ID/R2_ACCESS_KEY_ID/R2_SECRET_ACCESS_KEY/R2_BUCKET); "
              "nothing to do, using the local copy.")
        return 0
    if a.cmd == "status":
        print("\n".join(status()))
        return 0
    bad = [n for n in a.names if n not in FILES]
    if bad or not a.names:
        print(f"name(s) must be from: {', '.join(FILES)}", file=sys.stderr)
        return 2
    try:
        for n in a.names:
            if a.cmd == "pull":
                msg = pull(n, allow_missing=a.allow_missing)
            elif a.cmd == "seed":
                msg = seed(n)
            else:
                msg = push(n, force=a.force)
            print(f"{a.cmd} {n}: {msg}")
    except Conflict as e:
        print(f"::error title=R2 lock::{e}")
        return EXIT_CONFLICT
    except Guard as e:
        print(f"::error title=R2 guard::{e}")
        return EXIT_GUARD
    return 0


if __name__ == "__main__":
    sys.exit(main())
