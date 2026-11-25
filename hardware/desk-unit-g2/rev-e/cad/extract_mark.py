"""One-off: read Rev D's `mark` mesh (the wordmark recess floor) out of the Rev D record and write
its outline loops to mark_outline.json, in the Rev D face plane (u = x, v = up the face).

    python extract_mark.py /path/to/desk-unit-rev-d/index.html

wedge.py only reads mark_outline.json, so the Rev D file is not needed to rebuild Rev E.
"""
import base64
import json
import os
import sys
from collections import defaultdict
import numpy as np

REV_D_TILT = 35.0   # Rev D face leans 35° from vertical: n_out = (0, sin 35, cos 35)


def main(path):
    line = next(l for l in open(path, encoding="utf-8") if l.startswith("<script>window.SMYLTE_PARTS="))
    d = json.loads(line[len("<script>window.SMYLTE_PARTS="):].strip().rstrip(";").removesuffix("</script>").rstrip(";"))
    part = d["parts"]["mark"]
    pos = np.frombuffer(base64.b64decode(part["p"]), dtype="<f4").reshape(-1, 3).astype(float)
    idx = np.frombuffer(base64.b64decode(part["i"]), dtype="<u2" if part["w"] == 2 else "<u4").reshape(-1, 3)
    a = np.radians(REV_D_TILT)
    up = np.array([0, np.cos(a), -np.sin(a)])
    # merge coincident vertices
    key = np.round(pos, 4)
    uniq, inv = np.unique(key, axis=0, return_inverse=True)
    tri = inv.reshape(-1)[idx]
    uv = np.c_[uniq[:, 0], uniq @ up]
    e = np.sort(np.vstack([tri[:, [0, 1]], tri[:, [1, 2]], tri[:, [2, 0]]]), axis=1)
    u, c = np.unique(e, axis=0, return_counts=True)
    adj = defaultdict(list)
    for p, q in u[c == 1]:
        adj[p].append(q)
        adj[q].append(p)
    seen, loops = set(), []
    for s in adj:
        if s in seen:
            continue
        loop, prev, cur = [s], None, s
        seen.add(s)
        while True:
            nxt = [q for q in adj[cur] if q != prev and q not in seen]
            if not nxt:
                break
            prev, cur = cur, nxt[0]
            loop.append(cur)
            seen.add(cur)
        loops.append(uv[loop])

    def inside(pt, P):
        x, y = pt
        n, ins = len(P), False
        for i in range(n):
            x1, y1 = P[i]
            x2, y2 = P[(i + 1) % n]
            if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
                ins = not ins
        return ins
    # a loop lying inside another loop is a hole (the counter of the e); the rest are outlines
    parent = {i: next((j for j, M in enumerate(loops) if j != i and inside(L[0], M)), None)
              for i, L in enumerate(loops)}
    outers = [i for i in parent if parent[i] is None]
    period = max(outers, key=lambda i: loops[i][:, 0].mean())
    out = []
    for i, L in enumerate(loops):
        if parent[i] is None:
            kind, group = ("period" if i == period else "outer"), i
        else:
            kind, group = "hole", parent[i]
        out.append({"kind": kind, "group": int(group), "uv": np.round(L, 4).tolist()})
    json.dump({"source": "Rev D index.html, part `mark`, projected on its face plane (u = x, v = up the face)",
               "loops": out}, open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "mark_outline.json"), "w"))
    print(len(out), "loops", [(o["kind"], len(o["uv"])) for o in out])


if __name__ == "__main__":
    main(sys.argv[1])
