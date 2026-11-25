"""Round 6: weekday effects (Saturday under-performs normal; E8a). Monthly folds, same rows as round 5."""
import sys, pandas as pd
import run_round5 as R
def add_dow(d):
    dow = d.dep.dt.day_of_week
    for k, nm in ((4, "fri"), (5, "sat"), (6, "sun")):
        d[nm] = (dow == k).astype(float)
    d["wkend"] = d.sat + d.sun
    return d
_load = R.load5
R.load5 = lambda L: add_dow(_load(L))
R.EXPS = {"C1_+dow_monthly": dict(feats=R.F4 + ["fri", "sat", "sun", "wkend"], fold="monthly")}
R.main(leads=tuple(int(x) for x in sys.argv[1].split(",")))
