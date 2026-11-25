import importlib.util
import io
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest
from botocore.exceptions import ClientError

spec = importlib.util.spec_from_file_location("r2db", Path(__file__).resolve().parents[1] / "scripts" / "r2db.py")
R = importlib.util.module_from_spec(spec)
spec.loader.exec_module(R)


def _err(status, code):
    return ClientError({"Error": {"Code": code}, "ResponseMetadata": {"HTTPStatusCode": status}}, "op")


class FakeR2:
    """Enough of the S3 API for r2db, with R2's conditional-write semantics."""
    def __init__(self):
        self.objs, self.n = {}, 0

    def _etag(self):
        self.n += 1
        return f'"e{self.n}"'

    def head_object(self, Bucket, Key):
        if Key not in self.objs:
            raise _err(404, "404")
        body, etag = self.objs[Key]
        return {"ETag": etag, "ContentLength": len(body), "LastModified": "t"}

    def get_object(self, Bucket, Key, IfMatch=None):
        body, etag = self.objs[Key]
        if IfMatch and IfMatch != etag:
            raise _err(412, "PreconditionFailed")
        return {"Body": io.BytesIO(body), "ETag": etag}

    def put_object(self, Bucket, Key, Body, IfMatch=None, IfNoneMatch=None):
        cur = self.objs.get(Key)
        if IfNoneMatch == "*" and cur is not None:
            raise _err(412, "PreconditionFailed")
        if IfMatch is not None and (cur is None or cur[1] != IfMatch):
            raise _err(412, "PreconditionFailed")
        data = Body.read() if hasattr(Body, "read") else Body
        self.objs[Key] = (data, self._etag())
        return {"ETag": self.objs[Key][1]}

    def list_objects_v2(self, Bucket, Prefix):
        return {"Contents": [{"Key": k} for k in sorted(self.objs) if k.startswith(Prefix)]}

    def delete_object(self, Bucket, Key):
        self.objs.pop(Key, None)


def _db(path, rows=200):
    c = sqlite3.connect(path)
    c.execute("CREATE TABLE trips (id INTEGER PRIMARY KEY, x TEXT)")
    c.executemany("INSERT INTO trips (x) VALUES (?)", [("y" * 200,)] * rows)
    c.commit(); c.close()


def _kw(tmp_path, s3):
    return {"s3": s3, "bucket": "b", "root": tmp_path, "state_path": tmp_path / "state.json"}


def test_first_push_then_pull_round_trip(tmp_path):
    s3 = FakeR2()
    _db(tmp_path / "tracker.db")
    assert R.pull("tracker.db", allow_missing=True, **_kw(tmp_path, s3)) == "missing"
    R.push("tracker.db", **_kw(tmp_path, s3))
    assert "db/tracker.db" in s3.objs
    (tmp_path / "tracker.db").unlink()
    R.pull("tracker.db", **_kw(tmp_path, s3))
    assert sqlite3.connect(tmp_path / "tracker.db").execute("SELECT COUNT(*) FROM trips").fetchone()[0] == 200


def test_push_refuses_when_someone_else_wrote(tmp_path):
    s3 = FakeR2()
    _db(tmp_path / "tracker.db")
    R.pull("tracker.db", allow_missing=True, **_kw(tmp_path, s3))
    R.push("tracker.db", **_kw(tmp_path, s3))
    R.pull("tracker.db", **_kw(tmp_path, s3))
    s3.objs["db/tracker.db"] = (s3.objs["db/tracker.db"][0], '"other-job"')   # concurrent writer
    with pytest.raises(R.Conflict):
        R.push("tracker.db", **_kw(tmp_path, s3))
    assert s3.objs["db/tracker.db"][1] == '"other-job"'


def test_first_push_never_replaces_an_object_created_meanwhile(tmp_path):
    s3 = FakeR2()
    _db(tmp_path / "tracker.db")
    R.pull("tracker.db", allow_missing=True, **_kw(tmp_path, s3))
    s3.objs["db/tracker.db"] = (b"x" * 10, '"someone"')
    with pytest.raises(R.Conflict):
        R.push("tracker.db", **_kw(tmp_path, s3))


def test_guards_unpulled_and_shrunken_db(tmp_path):
    s3 = FakeR2()
    _db(tmp_path / "tracker.db")
    with pytest.raises(R.Guard):            # never pulled: no lock ETag
        R.push("tracker.db", **_kw(tmp_path, s3))
    R.pull("tracker.db", allow_missing=True, **_kw(tmp_path, s3))
    R.push("tracker.db", **_kw(tmp_path, s3))
    R.pull("tracker.db", **_kw(tmp_path, s3))
    (tmp_path / "tracker.db").unlink()
    _db(tmp_path / "tracker.db", rows=1)    # a fresh near-empty DB
    with pytest.raises(R.Guard):
        R.push("tracker.db", **_kw(tmp_path, s3))
    R.push("tracker.db", force=True, **_kw(tmp_path, s3))


def test_backups_one_per_day_pruned(tmp_path):
    s3 = FakeR2()
    _db(tmp_path / "tracker.db")
    R.pull("tracker.db", allow_missing=True, **_kw(tmp_path, s3))
    for day in (1, 2, 2, 20):
        R.push("tracker.db", now=datetime(2026, 12, day, tzinfo=timezone.utc), **_kw(tmp_path, s3))
    R.push("tracker.db", now=datetime(2027, 1, 15, tzinfo=timezone.utc), **_kw(tmp_path, s3))
    backups = sorted(k for k in s3.objs if k.startswith("backups/"))
    assert backups == ["backups/db/tracker.db/2026-12-20.db", "backups/db/tracker.db/2027-01-15.db"]


def test_unconfigured_is_a_no_op(monkeypatch, capsys):
    for k in ("R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET"):
        monkeypatch.setenv(k, "")
    monkeypatch.setattr(R, "_env", lambda: {k: None for k in ("a", "b")})
    assert R.main(["push", "tracker.db"]) == 0
    assert "not configured" in capsys.readouterr().out
    assert R.main(["configured"]) == 1


def test_seed_only_when_absent(tmp_path):
    s3 = FakeR2()
    _db(tmp_path / "tracker.db")
    R.seed("tracker.db", **_kw(tmp_path, s3))
    with pytest.raises(R.Conflict):
        R.seed("tracker.db", **_kw(tmp_path, s3))
    R.push("tracker.db", **_kw(tmp_path, s3))     # seed recorded the ETag, so push works
