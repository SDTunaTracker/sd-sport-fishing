"""Retry/backoff, archive recovery parser, rolling window, and alert de-duplication."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
import requests

from src import alerts, net
from src.completeness import Problem
from src.deep_backfill import SDFR_URL, SOCAL_URL, parse_archive_day

# ── net ───────────────────────────────────────────────────────────────────────

def test_is_network_error():
    assert net.is_network_error("ConnectionError: ... NameResolutionError(...getaddrinfo failed)")
    assert not net.is_network_error("ValueError: page layout changed")
    assert not net.is_network_error(None)


def test_wait_for_network_waits_then_succeeds():
    calls = iter([False, False, True])
    slept = []
    waited = net.wait_for_network(["h"], timeout=60, interval=5,
                                  sleep=slept.append, resolver=lambda h: next(calls))
    assert waited == 10 and slept == [5, 5]


def test_wait_for_network_gives_up():
    assert net.wait_for_network(["h"], timeout=10, interval=5,
                                sleep=lambda s: None, resolver=lambda h: False) is None


class _Resp:
    def __init__(self, code):
        self.status_code = code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}", response=self)


class _Session:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = 0

    def get(self, url, **kw):
        self.calls += 1
        o = self.outcomes.pop(0)
        if isinstance(o, Exception):
            raise o
        return _Resp(o)


def test_get_with_retry_recovers_from_dns_and_503():
    s = _Session([requests.ConnectionError("NameResolutionError"), 503, 200])
    delays = []
    r = net.get_with_retry("u", session=s, attempts=4, backoff=5, sleep=delays.append)
    assert r.status_code == 200 and s.calls == 3 and delays == [5, 10]


def test_get_with_retry_does_not_retry_404():
    s = _Session([404, 200])
    with pytest.raises(requests.HTTPError):
        net.get_with_retry("u", session=s, sleep=lambda d: None)
    assert s.calls == 1


def test_get_with_retry_gives_up():
    s = _Session([requests.ConnectionError("x")] * 3)
    with pytest.raises(requests.ConnectionError):
        net.get_with_retry("u", session=s, attempts=3, sleep=lambda d: None)


# ── main._scrape_with_retry ───────────────────────────────────────────────────

def test_scrape_with_retry_retries_only_network_failures(monkeypatch):
    from src import main
    a, b, c = object(), object(), object()
    state = {"b": 0}

    def fake_scrape_all(sources, target_date=None, known_boats=None):
        out = []
        for s in sources:
            if s is a:
                out.append((a, ["t"], None, None))
            elif s is b:
                state["b"] += 1
                err = None if state["b"] >= 3 else "ConnectionError: NameResolutionError"
                out.append((b, [] if err else ["t"], None, err))
            else:
                out.append((c, [], None, "ValueError: layout changed"))
        return out

    monkeypatch.setattr(main, "scrape_all", fake_scrape_all)
    res = main._scrape_with_retry([a, b, c], None, [], sleep=lambda d: None)
    assert res[0][3] is None
    assert res[1][3] is None and state["b"] == 3
    assert res[2][3].startswith("ValueError")  # not retried: not a network error


# ── archive parser ────────────────────────────────────────────────────────────

_ROW = """<tr><td><a href="/charter_boats/x.php"><b>{boat}</b></a><br/>
<a href="/landings/{slug}.php">{landing}</a><br/>San Diego, CA</td>
<td>{anglers} Anglers<br/><a href="?select=1">{trip}</a></td><td>{fish}</td><td></td></tr>"""


def _page(*rows):
    return "<html><body><div class='panel'><h2>X Fish Counts</h2><table>" + \
        "".join(_ROW.format(**r) for r in rows) + "</table></div></body></html>"


def test_parse_archive_day_maps_landings_and_counts():
    html = _page(
        dict(boat="Grande", slug="h&m_landing", landing="H&M Landing", anglers=17,
             trip="Full Day Offshore", fish="1 Skipjack Tuna, 7 Yellowfin Tuna, 3 Yellowtail Released"),
        dict(boat="Dolphin", slug="fishermans_landing", landing="Fisherman's Landing",
             anglers=12, trip="1/2 Day AM", fish="30 Sand Bass"),
        dict(boat="Nope", slug="somewhere_else", landing="Unknown Landing", anglers=5,
             trip="Full Day", fish="1 Yellowtail"),
    )
    trips = parse_archive_day(html, "2026-10-15", SDFR_URL)
    by = {t["boat"]: t for t in trips}
    assert set(by) == {"Grande", "Dolphin"}
    g = by["Grande"]
    assert (g["landing"], g["region"], g["anglers"], g["yellowfin"], g["yellowtail"]) == \
        ("H&M Landing", "san_diego", 17, 7, 0)  # released fish are not counted
    assert g["source"] == "fish_count_page" and g["source_url"].endswith("date=2026-10-15")
    assert by["Dolphin"]["is_half_day"] == 1


def test_parse_archive_day_resolves_socal_by_slug():
    html = _page(dict(boat="Amigo", slug="22nd_street_landing", landing="22nd Street Landing",
                      anglers=10, trip="2 Day", fish="36 Yellowfin Tuna"))
    (t,) = parse_archive_day(html, "2026-10-15", SOCAL_URL)
    assert t["landing"] == "22nd Street Landing" and t["region"] == "oc_la"


# ── alerts ────────────────────────────────────────────────────────────────────

def test_alert_lifecycle_new_digest_recovered(tmp_path):
    state = tmp_path / "s.json"
    sent = []
    send = lambda subj, body, sms: sent.append(subj)  # noqa: E731
    t0 = datetime(2026, 11, 24, 12, tzinfo=timezone.utc)
    p = Problem("scrape:H&M Landing", "trips", "critical", "H&M: no scrape")

    a = alerts.process([p], state_path=state, now=t0, send=send)
    assert a["new"] == [p.key] and len(sent) == 1 and "BROKEN" in sent[0]

    alerts.process([p], state_path=state, now=t0 + timedelta(hours=1), send=send)
    assert len(sent) == 1  # no repeat within the day

    alerts.process([p], state_path=state, now=t0 + timedelta(hours=25), send=send)
    assert len(sent) == 2 and "reminder" in sent[1]

    a = alerts.process([], state_path=state, now=t0 + timedelta(hours=26), send=send)
    assert a["recovered"] == [p.key] and "recovered" in sent[2]

    alerts.process([], state_path=state, now=t0 + timedelta(hours=27), send=send)
    assert len(sent) == 3


def test_deliver_without_config_is_a_noop():
    cfg = alerts.Config(None, None, None, 465, None, None, None)
    assert alerts.deliver("s", "b", "t", cfg) == []


def test_released_fish_are_not_counted_as_landed():
    from src import parse as P
    cols, other_fish, unknowns = P.extract_extended_species(
        {"Calico Bass": 5, "Calico Bass Released": 40, "Sand Bass Released": 3,
         "Spiny Lobster Released": 7, "Blue Perch": 2})
    assert cols["calico_bass"] == 5
    assert cols["sand_bass"] == 0
    assert other_fish == 2
    assert unknowns == [("Blue Perch", 2)]


def test_ocla_schedule_sources_are_capped():
    from src.schedule import SOURCES
    oc = [s for s in SOURCES if s.region == "oc_la"]
    assert {s.name for s in oc} >= {"22nd Street Landing", "Pierpoint Landing",
                                     "Channel Islands Sportfishing"}
    assert all(s.max_pages and s.max_pages <= 10 for s in oc)


def test_polite_spacing_and_honest_ua():
    from src import polite
    polite._last.clear()
    t = [100.0]
    slept = []
    clock = lambda: t[0]
    sleep = lambda s: slept.append(s)
    assert polite.wait_turn("https://www.socalfishreports.com/a", sleep, clock) == 0
    assert polite.wait_turn("https://socalfishreports.com/b", sleep, clock) == polite.MIN_INTERVAL
    assert polite.wait_turn("https://www.fishcounts.com/x", sleep, clock) == 0
    assert polite.headers("https://www.socalfishreports.com/x", {"User-Agent": "Mozilla"})["User-Agent"] == polite.BOT_UA
    assert polite.headers("https://www.fishcounts.com/x", {"User-Agent": "Mozilla"})["User-Agent"] == "Mozilla"
    assert polite.MIN_INTERVAL >= 3


def test_archive_recovery_stops_on_block(tmp_path, monkeypatch):
    import sqlite3
    from datetime import date
    from src import deep_backfill as DB
    calls = []

    def fake_fetch(session, base, d, **kw):
        calls.append(d)
        raise DB.ArchiveBlockedError("bot check")

    monkeypatch.setattr(DB, "fetch_archive_day", fake_fetch)
    conn = sqlite3.connect(tmp_path / "t.db")
    conn.execute("CREATE TABLE trips (date TEXT, boat TEXT, landing TEXT, trip_length TEXT,"
                 " anglers INTEGER, source TEXT)")
    rep = DB.recover_range(conn, date(2026, 11, 1), date(2026, 11, 5))
    assert rep.get("blocked") and len(calls) == 1
    # a second run inside the cooldown makes no request at all
    rep2 = DB.recover_range(conn, date(2026, 11, 1), date(2026, 11, 5))
    assert rep2.get("blocked") and len(calls) == 1
