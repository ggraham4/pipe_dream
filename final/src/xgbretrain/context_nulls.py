"""WO-43 post-hoc DESCRIPTIVE (not gated, not pre-registered): rank-IC and top-5 volq
for the 10 null score sets, so the ungated context numbers in step2_results.json have a
matched comparison. Output: final/out/xgbretrain/context_nulls.json"""
import json
import numpy as np
import evaluate as E

U, all_dates, spy = E.load_U("cap2000")
book = E.Book(U)
tickers = json.loads((E.STORE / "tickers.json").read_text())
out = {}
for r in ["arm0", "arm1", "arm2"] + sum(E.NULLS.values(), []):
    s, _ = E.load_scores(r, U, tickers)
    ic = book.rank_ic(s)
    t5, _ = E.summarize(E.series(book.picks(s, kind="top5"), all_dates, spy))
    out[r] = {"rank_ic": float(ic.mean()), "top5_excess": t5["excess_mean40"]}
    print(r, out[r], flush=True)
for a in E.ARMS:
    n = E.NULLS[a]
    out[f"{a}_null_summary"] = {k: [float(np.mean([out[x][k] for x in n])), float(np.std([out[x][k] for x in n], ddof=1))]
                                for k in ("rank_ic", "top5_excess")}
(E.OUTD / "context_nulls.json").write_text(json.dumps(out, indent=1))
