"""Paddle Tracker: race list, race courses, race-day conditions and paddler profiles.

Portable on purpose (the owner plans a separate Paddle Tracker site):
  web/api/v1/paddle_races.json            race list, hand-maintained (races.py edits it)
  web/api/v1/paddle_courses/<id>.geojson  course per race distance (course.py)
  web/api/v1/paddle_race_forecast.json    upcoming races, written by forecast.py
  web/api/v1/paddle_race_conditions.json  past races' race-day wind, written by conditions.py
  data/paddle/paddle_{paddlers,results}.json  hand-entered profiles/results (not deployed)
  web/api/v1/paddle_people.json           public copy, hidden paddlers removed (results.py build)
  web/paddle-races.jsx, web/paddle-paddlers.jsx, web/paddle-races.css   front end (prefix pr-)

PaddleGuru's terms forbid automated access: nothing is scraped from it, every
race links to its PaddleGuru page, and results are typed in by hand.
Live data comes through src/surf (imported, not copied): ECMWF wind via
Open-Meteo, NOAA tide-current predictions, CDIP MOP swell and buoy SST; past
races use the Open-Meteo ERA5 archive.
"""
