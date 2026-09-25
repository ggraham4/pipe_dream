"""
Nested industry taxonomies, and the matched-random controls that make
comparing them honest.

Round 13 established that essentially all of the deployed model's performance
is a sector bet, neutralising on 11 GICS-style sectors. Gabe's question
(2026-09-16): is the bet actually finer than that? Healthcare is not one thing
-- DNA services and medical equipment are different businesses.

Four usable levels, all already present in data/sharadar/tickers_master.csv:

    sector          11   the Round 13 level
    famaindustry    48   Fama-French 48, the academic standard
    sic2            64   SIC major group, derived as siccode // 100
    industry       136   Morningstar - "Software - Application"
    (sic3 209, sicindustry 314 exist but are NOT usable -- see below)

--------------------------------------------------------------------------
WHY FINER IS NOT AUTOMATICALLY BETTER, AND WHY THE CONTROL IS THE POINT
--------------------------------------------------------------------------
Neutralising means residualising returns on group dummies. More groups means
more dummies, and more dummies always removes more variance -- including
variance that has nothing to do with industry. On a 1,665-name cross-section,
11 sectors cost 0.7% of the degrees of freedom and 314 SIC industries cost 19%.
A finer taxonomy can therefore look like it "explains more of the edge" purely
by fitting better, which would be the opposite of the finding it appears to be.

So every level is compared against a RANDOM PARTITION with the same number of
groups and the same size distribution. The random partition has identical
degrees of freedom and no industry content whatever. Only the excess of the
real taxonomy over its matched control is evidence about taxonomy.

The random partition is drawn ONCE per level and per seed and held fixed across
all dates. Redrawing per date would let a name change groups between windows,
which is not what an industry classification does and would add noise the real
taxonomy does not have.

--------------------------------------------------------------------------
WHY sic3 AND sicindustry ARE EXCLUDED
--------------------------------------------------------------------------
Median group size 3, and only 72-85% of names land in a group with at least 5
members (build_design folds thinner groups into the baseline, so their industry
information is silently discarded). A level that throws away a quarter of the
cross-section before the comparison starts cannot be compared with one that
keeps all of it. They are reported by describe() so the exclusion is visible,
not assumed.
"""
from __future__ import annotations

from functools import lru_cache

import numpy as np
import pandas as pd

from sweep.factors import TICKERS_MASTER, _base_ticker

# ordered coarse -> fine
LEVELS = ["sector", "famaindustry", "sic2", "industry"]
EXCLUDED = ["sic3", "sicindustry"]     # too thin to NEUTRALISE on; see docstring
ALL_LEVELS = ["sector", "famaindustry", "sic2", "industry", "sic3", "sicindustry"]


# Missing values must be detected with pd.isna, never by relying on
# .astype(str) to turn them into the literal string "nan".
#
# Under pandas' object dtype, Series.astype(str) maps NaN -> "nan" and a
# downstream `(v or "").strip()` is safe. Under the newer Arrow-backed `str`
# dtype it PRESERVES the missing value, so a float NaN comes out the other
# side -- and float("nan") is truthy in Python, so `v or ""` hands the NaN
# straight to .strip() and raises. The behaviour therefore depends on the
# pandas version, which is how this passed on one machine and failed on
# another with the same CSV. Never infer missingness from a string
# conversion.
_MISSING = {"", "nan", "none", "<na>", "null", "na"}


def _label(v) -> str:
    """One cell -> a clean label, or "" if it is missing under any dtype."""
    if v is None or pd.isna(v):
        return ""
    s = str(v).strip()
    return "" if s.lower() in _MISSING else s


# Cached: the app's sector view builds six levels plus six display maps on
# every rerun, and each one re-read a ~20k-row CSV. The file is static for a
# session. Returned objects are treated as read-only by every caller here;
# nothing mutates a map in place.
@lru_cache(maxsize=1)
def _table():
    t = pd.read_csv(TICKERS_MASTER, low_memory=False)
    sic = pd.to_numeric(t["siccode"], errors="coerce")
    # Keep these numeric-with-NA; _label() renders them and drops the NAs, so
    # the rollups follow the same missingness path as every other column.
    t["sic2"] = (sic // 100).astype("Int64")
    t["sic3"] = (sic // 10).astype("Int64")
    return t


@lru_cache(maxsize=None)
def load(level: str) -> dict:
    """ticker -> group label at `level`."""
    if level not in LEVELS + EXCLUDED:
        raise ValueError(f"level must be one of {LEVELS + EXCLUDED}")
    t = _table()
    out = {}
    for tk, v in zip(t["ticker"].tolist(), t[level].tolist()):
        lab = _label(v)
        if lab and _label(tk):
            out[str(tk)] = lab
    return out


@lru_cache(maxsize=None)
def sic_names(digits: int) -> dict:
    """Human-readable label for each SIC rollup code.

    sic2 and sic3 are numeric codes -- "38", "384" -- which are useless in a UI.
    Rather than hardcode an SIC name table, each code is labelled by the MODAL
    4-digit industry name among its members, which is derived from the same
    file and stays correct if the data changes. "38 · Surgical & Medical
    Instruments & Apparatus" is the most common thing in major group 38, not a
    definition of it, and the label says so by leading with the code.
    """
    t = _table()
    col = "sic2" if digits == 2 else "sic3"
    out = {}
    sub = t[[col, "sicindustry"]].copy()
    sub["code"] = [_label(v) for v in sub[col]]
    sub["name"] = [_label(v) for v in sub["sicindustry"]]
    sub = sub[(sub["code"] != "") & (sub["name"] != "")]
    for code, g in sub.groupby("code"):
        modal = g["name"].value_counts()
        if len(modal):
            out[code] = f"{code} · {modal.index[0]}"
    return out


@lru_cache(maxsize=None)
def display_label_map(level: str) -> dict:
    """ticker -> label for DISPLAY. Same grouping as load(), but SIC rollups
    carry a readable name instead of a bare number."""
    m = load(level)
    if level not in ("sic2", "sic3"):
        return m
    names = sic_names(2 if level == "sic2" else 3)
    return {k: names.get(v, v) for k, v in m.items()}


def matched_random(real: dict, seed: int = 0) -> dict:
    """A random partition with the SAME group-size distribution as `real`.

    Tickers are shuffled and dealt into groups of exactly the real sizes, so
    the control matches on both group count and size profile -- the two things
    that determine how much variance a set of dummies can absorb. Anything the
    real taxonomy achieves beyond this is industry information rather than
    degrees of freedom.
    """
    rng = np.random.default_rng(seed)
    keys = np.array(sorted(real))
    sizes = pd.Series(list(real.values())).value_counts().to_numpy()
    rng.shuffle(keys)
    out, i = {}, 0
    for gi, n in enumerate(sizes):
        for k in keys[i:i + n]:
            out[str(k)] = f"rand{gi}"
        i += n
    for k in keys[i:]:                      # rounding remainder
        out[str(k)] = f"rand{len(sizes)-1}"
    return out


def describe(universe, min_per_group=5):
    """Group-size profile of every level on one cross-section, including the
    excluded ones, so the exclusion is a visible decision."""
    rows = []
    for lvl in LEVELS + EXCLUDED:
        m = load(lvl)
        labs = [m.get(_base_ticker(x), "") for x in universe]
        labs = [l for l in labs if l]
        vc = pd.Series(labs).value_counts()
        big = vc[vc >= min_per_group]
        rows.append({"level": lvl, "groups": len(vc),
                     "median_size": int(vc.median()) if len(vc) else 0,
                     "min_size": int(vc.min()) if len(vc) else 0,
                     f"groups_ge{min_per_group}": len(big),
                     "names_retained": (big.sum() / len(labs)) if len(labs) else 0,
                     "dof_share": len(big) / max(len(universe), 1),
                     "usable": lvl in LEVELS})
    return pd.DataFrame(rows)


def self_test():
    """Verify the control matches what it claims to match, and that label
    cleaning survives both pandas string dtypes."""
    import numpy as _np
    assert _label(float("nan")) == "", "float NaN must clean to empty"
    assert _label(None) == "" and _label(pd.NA) == ""
    assert _label("nan") == "" and _label("  Biotechnology ") == "Biotechnology"
    assert _label(3841) == "3841"
    for lvl in LEVELS + EXCLUDED:
        m = load(lvl)
        bad = [k for k, v in m.items() if not isinstance(v, str) or not v]
        assert not bad, f"{lvl}: {len(bad)} unusable labels, e.g. {bad[:3]}"
    print(f"label cleaning: ok across {len(LEVELS + EXCLUDED)} levels "
          f"(pandas {pd.__version__}, '{_table()['sector'].dtype}' dtype)")

    real = load("industry")
    rand = matched_random(real, seed=0)
    a = pd.Series(list(real.values())).value_counts().sort_values().to_numpy()
    b = pd.Series(list(rand.values())).value_counts().sort_values().to_numpy()
    assert set(real) == set(rand), "control covers a different ticker set"
    assert len(a) == len(b), f"group count differs: {len(a)} vs {len(b)}"
    assert np.array_equal(a, b), "group-size distribution differs"
    # and it must actually scramble membership
    same = np.mean([real[k].replace(" ", "") == rand[k] for k in real])
    print(f"self-test: {len(a)} groups, size profile identical, "
          f"{len(real):,} tickers, membership overlap {same:.4f}")
    r2 = matched_random(real, seed=1)
    agree = np.mean([rand[k] == r2[k] for k in real])
    # Two independent partitions agree at sum(p_i^2), NOT 1/n_groups: with
    # unequal group sizes a name is likelier to land in a big group twice.
    # 1/n is only right for equal sizes, and using it would make a correct
    # control look broken.
    p_i = a / a.sum()
    exp = float((p_i ** 2).sum())
    print(f"           two seeds agree on {agree:.4f} of assignments "
          f"(expect sum(p^2) = {exp:.4f}; 1/n = {1/len(a):.4f} is the "
          f"equal-size special case)")
    assert abs(agree - exp) < 0.02, f"agreement {agree:.4f} vs expected {exp:.4f}"
    print("PASSED")


if __name__ == "__main__":
    self_test()
