"""Paddle Tracker: race list, race courses and race-day conditions.

Portable on purpose (the owner plans a separate Paddle Tracker site):
  web/api/v1/paddle_races.json           hand-maintained race list (PaddleGuru forbids scraping)
  web/api/v1/paddle_courses/<id>.geojson hand-drawn course per race distance
  web/api/v1/paddle_race_forecast.json   written by `python -m src.paddle.forecast`
  web/paddle-races.jsx                   front end (CSS prefix `pr-`)

Live data comes only through src/surf (imported, not copied): ECMWF wind via
Open-Meteo, NOAA tide-current predictions, CDIP MOP swell and buoy SST.
"""
