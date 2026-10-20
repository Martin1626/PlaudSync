"""Calibrate FLAG_THRESHOLD from the spike embedding cache (local only, no API calls).

For each labelled row: cosine against the centroid of the same person's rows from OTHER recordings.
Persons with < 2 recordings are skipped. Names are masked as P01...

    python scripts/calibrate_flag_threshold.py
"""
from __future__ import annotations

import os
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

NPZ = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "plaudsync" / "spike_speaker_cache" / "embeddings_campplus.npz"
MAX_FLAG_SHARE = 0.05


def main() -> int:
    d = np.load(NPZ)
    rec, truth, emb = d["rec_id"], d["truth"], d["emb"]
    rows_of: dict[str, list[int]] = defaultdict(list)
    for i, t in enumerate(truth):
        if str(t):
            rows_of[str(t)].append(i)
    alias = {n: f"P{k:02d}" for k, n in enumerate(sorted(rows_of, key=lambda n: -len(rows_of[n])), 1)}
    scores: list[tuple[float, str]] = []
    for name, idx in rows_of.items():
        if len({str(rec[i]) for i in idx}) < 2:
            continue
        for i in idx:
            others = [j for j in idx if rec[j] != rec[i]]
            c = emb[others].mean(axis=0)
            c /= np.linalg.norm(c) + 1e-9
            scores.append((float(c @ (emb[i] / (np.linalg.norm(emb[i]) + 1e-9))), alias[name]))
    vals = np.array([s for s, _ in scores])
    print(f"labelled rows scored: {len(vals)} (persons: {len({p for _, p in scores})})")
    for p in (1, 5, 10, 25):
        print(f"  p{p}: {np.percentile(vals, p):.3f}")
    print("rows below 0.60:")
    for s, p in sorted(scores):
        if s < 0.6:
            print(f"  {p}  {s:.3f}")
    best = None
    for th in np.arange(0.65, 0.35, -0.05):
        share = float((vals < th).mean())
        print(f"  th {th:.2f}: flags {share:.1%}")
        if best is None and share <= MAX_FLAG_SHARE:
            best = round(float(th), 2)
    print(f"FLAG_THRESHOLD = {best}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
