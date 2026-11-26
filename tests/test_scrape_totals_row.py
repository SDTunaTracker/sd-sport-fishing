"""Fish-count tables end each date with a "Dock Totals" row ("1 Boat | 1 Trip |
30 Anglers | <same fish>"). It repeats the boat rows, so it must not become a
trip, and it must not log "unparsable trip length '1 Trip'" (Daily Scrape run
45825358236 logged it for 10 landings on 2026-11-26 — no trips were lost).
"""
import logging
from datetime import date

from src import scrape as S

PAGE = """<table class="scale-table"><tbody>
<tr><td class="scale-title" colspan="4">Fish Counts for November 25th, 2026</td></tr>
<tr><td class="scale-head">Boat</td><td class="scale-head">Trip Type</td>
    <td class="scale-head">Anglers</td><td class="scale-head">Fish Count</td></tr>
<tr><td class="scale-data"><strong>Toronado</strong></td><td class="scale-data">Overnight</td>
    <td class="scale-data">30</td><td class="scale-data">209 Rockfish, 10 Bonito</td></tr>
<tr><td class="scale-data"><strong>Dolphin</strong></td><td class="scale-data">3/4 Day</td>
    <td class="scale-data">45</td><td class="scale-data">102 Skipjack Tuna, 16 Yellowfin Tuna</td></tr>
<tr><td class="scale-head" colspan="5">Pierpoint Landing Dock Totals</td></tr>
<tr><td class="scale-data">2 Boats</td><td class="scale-data">2 Trips</td>
    <td class="scale-data">75 Anglers</td><td class="scale-data">209 Rockfish, 102 Skipjack Tuna</td></tr>
<tr><td class="scale-foot" colspan="4">As of 2:30 PM November 25th, 2026</td></tr>
</tbody></table>"""


def test_totals_row_is_not_a_trip(caplog):
    with caplog.at_level(logging.WARNING, logger="src.scrape"):
        trips = S.parse_page(PAGE, "Pierpoint Landing", "https://example.test", region="oc_la")
    assert [(t["boat"], t["trip_length"]) for t in trips] == [("Toronado", "Overnight"), ("Dolphin", "Full Day")]
    assert all(t["date"] == "2026-11-25" for t in trips)
    assert "unparsable trip length" not in caplog.text


def test_is_totals_row():
    assert S._is_totals_row(["1 Boat", "1 Trip", "30 Anglers", "209 Rockfish"])
    assert S._is_totals_row(["3 Boats", "4 Trips", "120 Anglers", "x"])
    # Real trips whose labels say "Trip" stay data rows.
    assert not S._is_totals_row(["Tribute", "1.5 Day Trip", "24", "x"])
    assert not S._is_totals_row(["Producer", "Overnight Trip", "30", "x"])
