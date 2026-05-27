import sys
sys.path.insert(0, '.')
from src.scrape import SOURCES, scrape_landing

osc = next(s for s in SOURCES if s.name == 'Oceanside Sea Center')
trips, page_date, _ = scrape_landing(osc)
print(f"page_date: {page_date}")
print(f"trips parsed: {len(trips)}")
for t in trips[:10]:
    print(f"  {t['date']}  {t['boat']:20s}  {t['trip_length']:12s}  {t['anglers']}ang  trophy={t['trophy_count']}")
