import sqlite3
conn = sqlite3.connect("tracker.db")
conn.row_factory = sqlite3.Row

rows = conn.execute("SELECT * FROM forecast_accuracy_log ORDER BY date DESC LIMIT 30").fetchall()
if rows:
    errs = [r["error"] for r in rows]
    dirs = [r["correct_direction"] for r in rows]
    print("Accuracy log: %d days" % len(rows))
    print("  MAE: %.2f" % (sum(errs)/len(errs)))
    print("  Direction accuracy: %.1f%%" % (sum(dirs)/len(dirs)*100))
    print()

bt = conn.execute("SELECT * FROM backtest_results ORDER BY run_date DESC LIMIT 2").fetchall()
for r in bt:
    d = dict(r)
    print("Backtest %s: MAE=%s dir_acc=%s n=%s" % (d.get("run_date",""), d.get("mae"), d.get("direction_accuracy"), d.get("total_days")))
print()

fs = conn.execute("SELECT * FROM forecast_scores ORDER BY date DESC, segment LIMIT 8").fetchall()
if fs:
    print("Forecast scores (most recent):")
    for r in fs:
        d = dict(r)
        print("  %s %-8s A=%s B=%s C=%s ens=%s std=%s conf=%s" % (d["date"], d["segment"], d["model_a"], d["model_b"], d["model_c"], d["ensemble"], d["std_dev"], d["confidence"]))
else:
    print("No forecast_scores yet")
