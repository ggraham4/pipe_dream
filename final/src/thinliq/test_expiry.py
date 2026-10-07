"""WO-47 C: arm 2 selects expiries with the WO-35 holiday rule (run_wo_o1.accepted_expiries).
Offline; reads SPY dates only, runs nothing of arm 2.

    /opt/anaconda3/envs/pipe_dream/bin/python final/src/thinliq/test_expiry.py
"""
import inspect

import pandas as pd

import run_arm2 as A
W = A.W


def main():
    src = inspect.getsource(A.build_entries)
    assert "accepted_expiries(" in src, "build_entries must use W.accepted_expiries"
    assert "exp + pd.Timedelta(days=1))]" not in src, "pre-fix 3rd-Friday/Saturday filter still present"

    td = A.trading_days()
    gf = pd.Timestamp("2019-04-19")                       # Good Friday, a standard monthly expiry
    assert gf not in td and pd.Timestamp("2019-04-18") in td
    acc = W.accepted_expiries(gf, td)
    assert pd.Timestamp("2019-04-18") in acc and gf in acc and pd.Timestamp("2019-04-20") in acc

    normal = pd.Timestamp("2019-05-17")                  # ordinary 3rd Friday: no extra day
    assert W.accepted_expiries(normal, td) == [normal, normal + pd.Timedelta(days=1)]

    # the filter build_entries applies, on a toy chain
    ch = pd.DataFrame({"expiration": pd.to_datetime(["2019-04-18", "2019-04-19", "2019-04-20", "2019-04-26"])})
    kept = ch[ch.expiration.isin(W.accepted_expiries(gf, td))]
    assert list(kept.expiration.dt.strftime("%Y-%m-%d")) == ["2019-04-18", "2019-04-19", "2019-04-20"]
    old_rule = ch[(ch.expiration == gf) | (ch.expiration == gf + pd.Timedelta(days=1))]
    assert len(old_rule) == 2                            # the old rule missed 2019-04-18
    print("test_expiry: OK (Good Friday 2019-04-19 accepts 2019-04-18; ordinary month unchanged)")


if __name__ == "__main__":
    main()
