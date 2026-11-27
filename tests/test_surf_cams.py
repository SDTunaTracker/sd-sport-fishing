import json
from datetime import datetime, timedelta, timezone

import requests

from src.surf import cams as K
from src.surf.breaks import BREAKS
from src.surf.spots import SPOTS

NOW = datetime(2026, 11, 28, 14, 0, tzinfo=timezone.utc)
CAM = {"id": "x", "youtube": "abcdefghijk"}


class R:
    def __init__(self, code=200, body=None, content=b"", headers=None):
        self.status_code, self._body, self.content, self.headers = code, body, content, headers or {}

    def json(self):
        return self._body


def fake(oembed_code=200, thumb=b"frame-1", thumb_code=200, raise_on=None):
    def get(url, **kw):
        if raise_on and raise_on in url:
            raise requests.ConnectionError("down")
        if "oembed" in url:
            return R(oembed_code, {"title": "Cam"} if oembed_code == 200 else None)
        return R(thumb_code, content=thumb)
    return get


def test_online_when_embeddable():
    s = K.check_cam(CAM, None, NOW, get=fake())
    assert s["status"] == "online" and s["lastSeen"] == "2026-11-28T14:00:00Z" and s["title"] == "Cam"


def test_frozen_thumbnail_is_not_offline():
    # some live streams keep their start-of-stream thumbnail for months
    first = K.check_cam(CAM, None, NOW, get=fake(thumb=b"same"))
    nxt = K.check_cam(CAM, first, NOW + timedelta(days=3), get=fake(thumb=b"same"))
    assert nxt["status"] == "online"


def test_offline_when_thumbnail_gone():
    s = K.check_cam(CAM, {"status": "online", "lastSeen": "2026-11-27T14:00:00Z"}, NOW, get=fake(thumb_code=404))
    assert s["status"] == "offline" and s["lastSeen"] == "2026-11-27T14:00:00Z"


def test_offline_when_embedding_off_or_removed():
    assert K.check_cam(CAM, None, NOW, get=fake(oembed_code=401))["status"] == "offline"
    assert "embedding" in K.check_cam(CAM, None, NOW, get=fake(oembed_code=401))["reason"]
    assert K.check_cam(CAM, None, NOW, get=fake(oembed_code=404))["status"] == "offline"
    assert K.check_cam(CAM, None, NOW, get=fake(oembed_code=400))["status"] == "offline"


def test_failed_check_keeps_previous_status():
    prev = {"status": "online", "lastSeen": "2026-11-27T14:00:00Z"}
    s = K.check_cam(CAM, prev, NOW, get=fake(raise_on="oembed"))
    assert s["status"] == "online" and "checkError" in s and s["lastSeen"] == prev["lastSeen"]
    s = K.check_cam(CAM, prev, NOW, get=fake(oembed_code=503))
    assert s["status"] == "online"
    assert K.check_cam(CAM, None, NOW, get=fake(raise_on="ytimg"))["status"] == "unknown"


def test_run_writes_status_for_every_cam(tmp_path):
    cams = tmp_path / "c.json"
    cams.write_text(json.dumps({"cams": [{"id": "a", "youtube": "1"}, {"id": "b", "youtube": "2"}]}))
    out = tmp_path / "s.json"

    def get(url, **kw):
        if "oembed" in url and "v=2" in kw["params"]["url"]:
            raise RuntimeError("boom")   # unexpected crash in one cam
        return fake()(url, **kw)
    p = K.run(cams, out, now=NOW, get=get, pause=0)
    saved = json.loads(out.read_text())
    assert set(saved["cams"]) == {"a", "b"} and p["cams"]["a"]["status"] == "online"
    assert saved["cams"]["b"]["status"] == "unknown"


SKY = {"id": "s", "source": "skyline", "skyline": {"image": "https://embed.skylinewebcams.com/img/1.jpg"}}


def test_skyline_online_when_picture_recent():
    get = lambda url, **kw: R(200, content=b"x" * 5000, headers={"Last-Modified": "Sat, 28 Nov 2026 13:55:0 GMT"})
    s = K.check_cam(SKY, None, NOW, get=get)
    assert s["status"] == "online" and s["imageUpdated"] == "2026-11-28T13:55:00Z"


def test_skyline_offline_when_stale_or_placeholder():
    stale = lambda url, **kw: R(200, content=b"x" * 5000, headers={"Last-Modified": "Fri, 27 Nov 2026 01:00:00 GMT"})
    assert K.check_cam(SKY, None, NOW, get=stale)["status"] == "offline"
    tiny = lambda url, **kw: R(200, content=b"x" * 300)
    assert K.check_cam(SKY, None, NOW, get=tiny)["status"] == "offline"
    down = lambda url, **kw: (_ for _ in ()).throw(requests.ConnectionError("x"))
    assert K.check_cam(SKY, {"status": "online"}, NOW, get=down)["status"] == "online"


def test_cam_list_is_valid():
    data = json.loads(K.CAMS.read_text(encoding="utf-8"))
    ids = [c["id"] for c in data["cams"]]
    assert len(ids) == len(set(ids))
    spot_ids = {b["id"] for b in BREAKS} | {s[0] for s in SPOTS}
    for c in data["cams"]:
        # owner rule (2026-11-27): cams must show surf breaks, never a harbour or bay view
        assert c["kind"] == "surf" and c["covers"], c["id"]
        if c.get("source") == "skyline":
            sk = c["skyline"]
            assert sk["image"].startswith("https://embed.skylinewebcams.com/img/") and sk["page"] in sk["embedHtml"]
            assert sk["embedHtml"].startswith("<a href=") and sk["image"] in sk["embedHtml"]
        else:
            assert len(c["youtube"]) == 11
        assert c["operator"]["name"] and c["operator"]["url"].startswith(("https://www.youtube.com/", "https://www.skylinewebcams.com/"))
        for sid in c["covers"] + c["near"]:
            assert sid in spot_ids, (c["id"], sid)
    # cleared for embedding only: never Surfline / HDOnTap / Earth Watch Live
    blob = json.dumps(data["cams"]).lower()
    assert "surfline" not in blob and "hdontap" not in blob and "earth watch" not in blob
