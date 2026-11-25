import sqlite3
src = sqlite3.connect("file:C:/Users/Jenelle/Projects/sd-sport-fishing/tracker.db?mode=ro", uri=True)
dst = sqlite3.connect("data/tracker_snapshot.db")
src.backup(dst); dst.close(); src.close(); print("ok")
