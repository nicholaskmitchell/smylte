"""Checks: bed size, watertightness, minimum wall, overhangs, interference, re-measured key numbers,
and SVG sections. Rays are cast with a plain numpy Möller–Trumbore (no rtree in the CAD env)."""
import itertools
import math
import numpy as np
import trimesh
import manifold3d as mf
from scipy.spatial import cKDTree

from params import *  # noqa: F401,F403
from geom import S_DIR, N_DIR, N_OUT, unit, face_sn, m_from_mesh, m_arrays, m_cyl


# ------------------------------------------------------------------ rays
def raycast(V, F, O, D, chunk=None):
    """Nearest hit (t > 1e-6) of each ray against triangles; returns t (inf if none) and triangle index."""
    T0, T1, T2 = V[F[:, 0]], V[F[:, 1]], V[F[:, 2]]
    E1, E2 = T1 - T0, T2 - T0
    O, D = np.atleast_2d(O).astype(float), np.atleast_2d(D).astype(float)
    nT = len(F)
    chunk = chunk or max(1, int(3e6 // max(nT, 1)))
    tout = np.full(len(O), np.inf)
    iout = np.full(len(O), -1)
    for a in range(0, len(O), chunk):
        o, d = O[a:a + chunk, None, :], D[a:a + chunk, None, :]
        p = np.cross(d, E2[None])
        det = np.einsum("ijk,ijk->ij", np.broadcast_to(E1[None], p.shape), p)
        ok = np.abs(det) > 1e-12
        inv = np.where(ok, 1.0 / np.where(ok, det, 1), 0)
        s = o - T0[None]
        u = np.einsum("ijk,ijk->ij", s, p) * inv
        q = np.cross(s, np.broadcast_to(E1[None], s.shape))
        v = np.einsum("ijk,ijk->ij", np.broadcast_to(d, q.shape), q) * inv
        t = np.einsum("ijk,ijk->ij", np.broadcast_to(E2[None], q.shape), q) * inv
        hit = ok & (u >= -1e-9) & (v >= -1e-9) & (u + v <= 1 + 1e-9) & (t > 1e-6)
        t = np.where(hit, t, np.inf)
        k = np.argmin(t, axis=1)
        tout[a:a + chunk] = t[np.arange(len(k)), k]
        iout[a:a + chunk] = np.where(np.isfinite(tout[a:a + chunk]), k, -1)
    return tout, iout


def tri_normals_areas(V, F):
    c = np.cross(V[F[:, 1]] - V[F[:, 0]], V[F[:, 2]] - V[F[:, 0]])
    a = np.linalg.norm(c, axis=1)
    return c / np.maximum(a, 1e-18)[:, None], a / 2


# ------------------------------------------------------------------ per-part checks
def watertight(tm):
    m = m_from_mesh(tm.vertices, tm.faces)
    comps = len(m.decompose()) if m.status() == mf.Error.NoError else 0
    return {"watertight": bool(tm.is_watertight), "winding_consistent": bool(tm.is_winding_consistent),
            "manifold_ok": m.status() == mf.Error.NoError, "solids": comps,
            "ok": bool(tm.is_watertight and tm.is_winding_consistent and m.status() == mf.Error.NoError and comps == 1)}


def min_wall(mesh, per_face=3, seed=1, exclude=None):
    """Wall thickness between opposed surfaces: from sample points on every CAD face, a ray along
    the inward normal to the first exit whose normal is within ~25° of the ray (opposed faces)."""
    V, F, fid = mesh.V, mesh.F, mesh.fid
    N, A = tri_normals_areas(V, F)
    rng = np.random.default_rng(seed)
    pick = []
    for k in np.unique(fid):
        idx = np.nonzero((fid == k) & (A > 1e-6))[0]
        if len(idx) == 0:
            continue
        p = A[idx] / A[idx].sum()
        pick += list(rng.choice(idx, size=min(per_face, len(idx)), replace=False, p=p))
    pick = np.array(pick)
    C = V[F[pick]].mean(1)
    O = C - N[pick] * 1e-4
    t, hit = raycast(V, F, O, -N[pick])
    good = np.isfinite(t) & (hit >= 0)
    good[good] &= np.einsum("ij,ij->i", N[hit[good]], -N[pick][good]) > 0.9
    if not good.any():
        return None
    i = np.argmin(np.where(good, t, np.inf))
    out = {"mm": round(float(t[i]), 2), "at": [round(float(c), 1) for c in C[i]], "samples": int(good.sum())}
    if exclude is not None:
        keep = good & ~exclude(C)
        j = np.argmin(np.where(keep, t, np.inf))
        out["excluding"] = exclude.__doc__
        out["mm_excluding"] = round(float(t[j]), 2)
        out["at_excluding"] = [round(float(c), 1) for c in C[j]]
    return out


def overhangs(mesh_print):
    """Downward faces more than 45° from vertical (with OVERHANG_TOL), per CAD face, minus bridges:
    a region is a bridge if, just below it, rays along one horizontal axis hit the part on both sides
    within BRIDGE_MAX in total."""
    V, F, fid = mesh_print.V, mesh_print.F, mesh_print.fid
    N, A = tri_normals_areas(V, F)
    zmin = V[:, 2].min()
    lim = -math.sin(math.radians(OVERHANG_MAX + OVERHANG_TOL))   # n_z below this: > 45.5° from vertical
    bad = (N[:, 2] < lim) & (A > 1e-9)
    bad &= V[F][:, :, 2].max(1) > zmin + 0.02          # not the bed contact
    out = []
    for k in np.unique(fid[bad]):
        idx = np.nonzero(bad & (fid == k))[0]
        area = float(A[idx].sum())
        if area < 0.05:
            continue
        P = V[F[idx]].reshape(-1, 3)
        c = (V[F[idx]].mean(1) * A[idx, None]).sum(0) / A[idx].sum()
        xy = P[:, :2] - c[:2]
        w, vec = np.linalg.eigh(xy.T @ xy)
        ext = [float(np.ptp(xy @ vec[:, j])) for j in (0, 1)]
        bridge, span = False, None
        for j in (0, 1):
            d = np.r_[vec[:, j], 0.0]
            o = c - np.array([0, 0, 0.05])
            t1, _ = raycast(V, F, o, d)
            t2, _ = raycast(V, F, o, -d)
            if np.isfinite(t1[0]) and np.isfinite(t2[0]) and t1[0] + t2[0] <= BRIDGE_MAX:
                bridge, span = True, float(t1[0] + t2[0])
                break
        worst = float(90 - np.degrees(np.arccos(np.clip(-N[idx, 2], -1, 1))).min())
        out.append({"face": int(k), "area_mm2": round(area, 2), "worst_from_vertical": round(worst, 1),
                    "at": [round(float(x), 1) for x in c], "extent": [round(e, 1) for e in sorted(ext)],
                    "bridge": bridge, "bridge_span": None if span is None else round(span, 1)})
    return out


# ------------------------------------------------------------------ interference
INTENDED = {
    frozenset(["foam", "panel_glass"]): "foam preload: 1.0 pads compressed to 0.8 (§3.1)",
    frozenset(["rear_plate", "backer"]): "post preload, 0.1 into the backer (S6)",
    frozenset(["j2_pins", "pi_pcb"]): "press-fit pins in J2 (§4 option A)",
    frozenset(["j2_pins", "j2_housing"]): "Dupont housing on the J2 pins",
    frozenset(["pi_pins", "dupont"]): "Dupont housings on the header pins (§3.4)",
    frozenset(["key_switch", "key_socket"]): "Choc pins in the hot-swap sleeves, 1.4 deep (F5)",
    frozenset(["screws_pi", "rear_plate"]): "M2.5 thread-forming screws in the Ø2.2 pilots",
    frozenset(["screws_key", "key_carrier"]): "M2 thread-forming screws in the Ø1.7 pilots (F4)",
    frozenset(["panel_tail", "hat_parts"]): "panel tail inserted 3.7 into the FPC socket (§3.2)",
    frozenset(["inserts", "shell"]): "heat-set inserts melted into their Ø4.0 holes",
    frozenset(["screws_rear", "inserts"]): "M3 screws threaded into the inserts",
    frozenset(["j2_leads", "key_shoes"]): "the shoe's nose crushes the 0.6 stripped wire end onto the tab by 0.2 "
                                          "(item 6, the clamp)",
}


def interference(solids):
    names = list(solids)
    bbs = {k: np.array(solids[k].bounding_box()).reshape(2, 3) for k in names}
    rows = []
    for a, b in itertools.combinations(names, 2):
        A, B = bbs[a], bbs[b]
        if np.any(A[1] < B[0] - 1e-6) or np.any(B[1] < A[0] - 1e-6):
            continue
        v = (solids[a] ^ solids[b]).volume()
        if v > INTERFERENCE_MIN:
            why = INTENDED.get(frozenset([a, b]))
            rows.append({"a": a, "b": b, "mm3": round(v, 3), "intended": why is not None, "why": why or ""})
    return sorted(rows, key=lambda r: (r["intended"], -r["mm3"]))


# ------------------------------------------------------------------ key numbers re-measured
def _hits_along(tms, o, d):
    """Entry/exit distances along one ray for each named mesh."""
    out = {}
    for k, tm in tms.items():
        V, F = np.asarray(tm.vertices), np.asarray(tm.faces)
        ts = []
        o2 = np.array(o, float)
        travelled = 0.0
        for _ in range(12):
            t, _ = raycast(V, F, o2, d)
            if not np.isfinite(t[0]):
                break
            travelled += t[0]
            ts.append(travelled)
            o2 = o2 + d * (t[0] + 1e-5)
            travelled += 1e-5
        if ts:
            out[k] = [round(float(x), 3) for x in ts]
    return out


def measure(asm_tm, meta):
    """asm_tm: name → welded trimesh in the unit frame."""
    sh = asm_tm["shell"]
    lo, hi = sh.bounds
    km = {}
    km["overall"] = {"W": round(hi[0] - lo[0], 2), "D": round(hi[2] - lo[2], 2),
                     "H_from_desk": round(hi[1] - asm_tm["feet"].bounds[0][1], 2),
                     "W_with_key": round(asm_tm["keycap"].bounds[1][0] - lo[0], 2),
                     "note": "D is the shell; the M3 heads sit in P2's counterbores, inside its outer face (item 5)"}
    # depth stack at y 76 (the Pi's top edge), x = 40, rear to front
    d = np.array([0, 0, 1.0])
    o = np.array([40.0, 75.95, -10.0])
    names = ("rear_plate", "pi_pcb", "backer", "foam", "panel_glass", "panel_face", "shell")
    hits = _hits_along({k: asm_tm[k] for k in names}, o, d)
    stack = {k: [round(t - 10.0, 2) for t in v] for k, v in hits.items()}
    km["depth_stack_y76_x40"] = stack
    hits = _hits_along({k: asm_tm[k] for k in names}, np.array([84.5, 75.95, -10.0]), d)
    km["depth_stack_y76_x84.5_through_the_side_bezel"] = {k: [round(t - 10.0, 2) for t in v] for k, v in hits.items()}
    z_pcb_front = stack["pi_pcb"][1]
    z_backer = stack["backer"][0]
    km["cold_gap"] = {"pcb_front_z": z_pcb_front, "backer_rear_z": z_backer,
                      "gap_after_2.0_underside": round(z_backer - z_pcb_front - 2.0, 2), "spec": 7.62}
    # window: rays in the face plane from the window centre
    def win(n):
        sm = (WIN_OUT_S[0] + WIN_OUT_S[1]) / 2
        c = unit(0, sm, n)
        r = {}
        for lab, dv in (("x+", np.array([1.0, 0, 0])), ("x-", np.array([-1.0, 0, 0])), ("s+", S_DIR), ("s-", -S_DIR)):
            t, _ = raycast(np.asarray(sh.vertices), np.asarray(sh.faces), c, dv)
            r[lab] = round(float(t[0]), 2)
        return {"width": round(r["x+"] + r["x-"], 2), "s_from": round(sm - r["s-"], 2), "s_to": round(sm + r["s+"], 2)}
    km["window_front_n0.002"] = win(0.002)
    km["window_panel_side_n1.6"] = win(1.6)
    scr = np.array(meta["screen"])
    s_lo = face_sn(scr[0][1], scr[0][2])[0]
    s_hi = face_sn(scr[2][1], scr[2][2])[0]
    km["active_area"] = {"width": round(scr[1][0] - scr[0][0], 2), "s_from": round(s_lo, 2), "s_to": round(s_hi, 2),
                         "y_on_face_plane": [round(TOE_Y + COS * s_lo, 2), round(TOE_Y + COS * s_hi, 2)]}
    w0, w1 = km["window_front_n0.002"], km["window_panel_side_n1.6"]
    face_top_s = (hi[1] - TOE_Y) / COS
    km["bezels"] = {"side": round(HALF_W - w0["width"] / 2, 2), "top": round(face_top_s - w0["s_to"], 2),
                    "chin": round(w0["s_from"], 2),
                    "window_vs_active_margin": {"x": round((w1["width"] - (scr[1][0] - scr[0][0])) / 2, 2),
                                                "bottom": round(s_lo - w1["s_from"], 2), "top": round(w1["s_to"] - s_hi, 2)}}
    # key
    sw = asm_tm["key_switch"]
    cut_c = unit(HALF_W - 0.6, KEY_S, KEY_N)
    r = {}
    for lab, dv in (("s+", S_DIR), ("s-", -S_DIR), ("n+", N_DIR), ("n-", -N_DIR)):
        t, _ = raycast(np.asarray(sh.vertices), np.asarray(sh.faces), cut_c, dv)
        r[lab] = float(t[0])
    cap = asm_tm["keycap"]
    cap_c = cap.bounds.mean(0)
    cap_s, cap_n = face_sn(cap_c[1], cap_c[2])
    km["key"] = {"centre_y": round(float(cap_c[1]), 2), "centre_z": round(float(cap_c[2]), 2),
                 "centre_s": round(cap_s, 2), "centre_n": round(cap_n, 2),
                 "proud": round(float(cap.bounds[1][0] - HALF_W), 2),
                 "cut_s": round(r["s+"] + r["s-"], 2), "cut_n": round(r["n+"] + r["n-"], 2),
                 "cap_front_edge_behind_face": round(float(min(face_sn(v[1], v[2])[1] for v in cap.vertices)), 2),
                 "cap_lowest_y": round(float(cap.bounds[0][1]), 2)}
    # HAT header to the Pi's underside allowance (z 25.1)
    hh = asm_tm["hat_header"]
    km["hat_header_to_pi_underside_allowance"] = round(float(hh.bounds[0][2] - (PI_Z[1] + 2.0)), 2)
    # saddle to J2 housing
    km["saddle_to_j2_housing"] = round(float(asm_tm["j2_housing"].bounds[0][1] - SADDLE_TOP_Y), 2)
    # item 6: the shoe's nose on the stripped wire, along a ray down through the nose at each tab
    from printed import pilot_positions, groove_lines
    clamp = {}
    for lab, (ps, _), (dn, _, _) in zip(("tab_A", "tab_B"), pilot_positions(), groove_lines()):
        w0 = 6.0
        o = unit(P4_X[1] - w0, KEY_S + ps, KEY_N + dn)
        h = _hits_along({k: asm_tm[k] for k in ("key_shoes", "j2_leads", "key_socket")}, o, np.array([1.0, 0, 0]))
        nose = w0 - h["key_shoes"][1]
        wire_top, wire_bottom = w0 - h["j2_leads"][0], w0 - h["j2_leads"][1]
        tab = w0 - h["key_socket"][0]
        clamp[lab] = {"at_ds_dn": [round(ps, 2), round(dn, 2)], "nose_to_tab_gap": round(nose - tab, 2),
                      "wire_d": WIRE_D, "crush": round(WIRE_D - (nose - tab), 2),
                      "proxy_overlap_with_nose": round(wire_top - nose, 2), "proxy_above_tab": round(wire_bottom - tab, 2)}
    km["key_wire_clamp"] = clamp
    return km


# ------------------------------------------------------------------ item 1: webs and skins
def _boundary_points(cs, step=0.02):
    P = []
    for pg in cs.to_polygons():
        pg = np.asarray(pg, float)
        for a, b in zip(pg, np.roll(pg, -1, 0)):
            k = max(1, int(np.ceil(np.linalg.norm(b - a) / step)))
            P.append(a + (b - a) * np.linspace(0, 1, k, endpoint=False)[:, None])
    return np.vstack(P)


def through_openings(m, levels, clip):
    """Openings right through a wall. m is placed so the wall's through-axis is z; the open area of
    every slice at `levels`, intersected, inside the rectangle clip = (x0, y0, x1, y1)."""
    x0, y0, x1, y1 = clip
    box = mf.CrossSection.square((x1 - x0, y1 - y0)).translate((x0, y0))
    op = box
    for z in levels:
        op = op ^ (box - m.slice(float(z)))
    return [c for c in op.decompose() if c.area() > 0.01]


def webs(comps, limit, to3d):
    """Narrowest web between any two openings (boundary points every 0.02); to3d maps a 2D point
    to the unit frame for reporting."""
    pts = [_boundary_points(c) for c in comps]
    trees = [cKDTree(p) for p in pts]
    bb = [c.bounds() for c in comps]
    best, low = None, []
    for i, j in itertools.combinations(range(len(comps)), 2):
        a, b = bb[i], bb[j]
        if max(a[0] - b[2], b[0] - a[2], a[1] - b[3], b[1] - a[3]) > max(limit, 3.0):
            continue
        d, k = trees[j].query(pts[i])
        q = int(np.argmin(d))
        rec = {"mm": round(float(d[q]), 2), "at": [round(float(v), 1) for v in to3d((pts[i][q] + pts[j][k[q]]) / 2)]}
        if best is None or d[q] < best[0]:
            best = (float(d[q]), rec)
        if d[q] < limit:
            low.append(rec)
    return (best[1] if best else None), low


ROT_Y_UP = np.array([[1, 0, 0, 0], [0, 0, -1, 0], [0, 1, 0, 0]], float)   # (x, y, z) → (x, −z, y)


def web_walls(shell_m, plate_m):
    """The walls of P1 and P2 that carry more than one through-opening: (part, wall, openings, to3d).
    The face (the window) and the right flank (the key cutout) carry one each."""
    q = shell_m.transform(ROT_Y_UP)
    yf, yt = (TOE_Y + FLOOR_TOP) / 2, (LAND_UNDER + TOP_Y) / 2
    return [
        ("rear_plate", "plate", through_openings(plate_m, np.linspace(0.05, P2_T - 0.05, 39),
                                                 (-P2_X + 0.5, P2_Y[0] + 0.5, P2_X - 0.5, P2_Y[1] - 0.5)),
         lambda p: (p[0], p[1], P2_T / 2)),
        ("shell", "floor", through_openings(q, np.linspace(TOE_Y + 0.05, FLOOR_TOP - 0.05, 39),
                                            (-FLANK_IN + 0.1, -(_z_floor_front() - 0.2), FLANK_IN - 0.1, -0.6)),
         lambda p: (p[0], yf, -p[1])),
        ("shell", "top land", through_openings(q, np.linspace(LAND_UNDER + 0.05, TOP_Y - 0.05, 39),
                                               (-FLANK_IN + 0.1, -20.0, FLANK_IN - 0.1, -0.6)),
         lambda p: (p[0], yt, -p[1])),
    ]


def _z_floor_front():
    """z where the face plate's inner surface meets the floor top."""
    return TOE_Z - (WALL + SIN * (FLOOR_TOP - TOE_Y)) / COS


def web_check(walls):
    out = []
    for part, wall, comps, to3d in walls:
        best, low = webs(comps, WEB_MIN, to3d)
        out.append({"part": part, "wall": wall, "through_openings": len(comps),
                    "open_area_mm2": round(sum(c.area() for c in comps), 1),
                    "narrowest_web": best, "under_limit": low, "ok": not low})
    return out


def _first_segment(V, F, O, D, reach):
    """Entry and exit of the first solid segment along each ray (triangles near the rays only)."""
    E = O + D * reach
    lo, hi = np.minimum(O.min(0), E.min(0)) - 0.1, np.maximum(O.max(0), E.max(0)) + 0.1
    T = V[F]
    keep = np.all(T.max(1) >= lo, 1) & np.all(T.min(1) <= hi, 1)
    F2 = F[keep]
    Dm = np.broadcast_to(D, O.shape)
    t1, _ = raycast(V, F2, O, Dm)
    O2 = O + Dm * (np.where(np.isfinite(t1), t1, 0) + 1e-4)[:, None]
    t2, _ = raycast(V, F2, O2, Dm)
    return t1, t1 + 1e-4 + t2


def _grid(x0, x1, y0, y1, step):
    X, Y = np.meshgrid(np.arange(x0 + step / 2, x1, step), np.arange(y0 + step / 2, y1, step))
    return X.ravel(), Y.ravel()


def skin_probes():
    """Every recess in P1 and P2: rays from outside the part along the recess axis. A sample counts
    if the recess floor is where the ray meets it ("near": the first surface; "far": the exit of the
    first solid segment); the skin is that segment's length."""
    pr = []
    Z = np.array([0, 0, 1.0])

    def p2(name, x, y, floor_z, side, rule="skin"):
        x, y = np.asarray(x, float).ravel(), np.asarray(y, float).ravel()
        pr.append(dict(part="rear_plate", name=name, O=np.c_[x, y, np.full(len(x), -5.0)], D=Z,
                       floor=floor_z + 5.0, side=side, rule=rule))
    p2("header recess, inner face, 1.0 deep", *_grid(*RECESS_HEADER[0], *RECESS_HEADER[1], 0.5), P2_T - RECESS_DEPTH, "far")
    p2("J2 recess, inner face, 1.0 deep", *_grid(*RECESS_J2[0], *RECESS_J2[1], 0.5), P2_T - RECESS_DEPTH, "far")
    p2("band A outer recesses, 0.4 deep, y 80-86 (i 24-33)",
       *np.meshgrid([BAND_A_X[i] for i in BAND_A_SHORT_I], np.arange(BAND_A_RECESS_Y[0] + 0.3, BAND_A_Y_SHORT[0], 0.25)),
       OUTER_RECESS_DEPTH, "near")
    p2("band B outer recesses, 0.4 deep, x 4.4 and 8.8",
       *np.meshgrid(BAND_B_RECESS_X, np.arange(BAND_B_Y[0] + 0.3, BAND_B_Y[1] - 0.2, 0.25)), OUTER_RECESS_DEPTH, "near")
    a = np.linspace(0, 2 * np.pi, 24, endpoint=False)
    r = (P2_SCREW_D + P2_CBORE_D) / 4
    p2("screw counterbores, 6.0 x 1.8 from outside", [x + r * np.cos(a) for x, _ in BOSS_XY],
       [y + r * np.sin(a) for _, y in BOSS_XY], P2_CBORE_DEPTH, "near")
    # P1
    Y = np.array([0, 1.0, 0])
    rr, aa = np.meshgrid([0.0, 1.5, 3.0, 4.5, 6.0, 6.6], a)
    O = np.vstack([np.c_[x + (rr * np.cos(aa)).ravel(), np.full(rr.size, -5.0), z + (rr * np.sin(aa)).ravel()]
                   for x, z in FOOT_XZ])
    pr.append(dict(part="shell", name="foot locators, 13.5 x 0.2 in the floor underside", O=O, D=Y,
                   floor=5.0 + TOE_Y + FOOT_RING_DEPTH, side="near", rule="skin"))
    x, s = _grid(MARK_BOX_X[0] - 1.0, MARK_BOX_X[1] + 1.0, MARK_BOX_S[0] - 0.5, MARK_BOX_S[1] + 0.5, 0.3)
    pr.append(dict(part="shell", name="wordmark, 0.4 deep in the face", O=np.array([unit(a_, b_, -5.0) for a_, b_ in zip(x, s)]),
                   D=N_DIR, floor=5.0 + MARK_DEPTH, side="near", rule="own rule (item 2: layer-1 slice)"))
    h = (KEY_CUT + KEY_CBORE) / 4
    t = np.linspace(-h, h, 11)
    ds = np.r_[np.full(11, -h), np.full(11, h), t, t]
    dn = np.r_[t, t, np.full(11, -h), np.full(11, h)]
    pr.append(dict(part="shell", name="key counterbore, 16.0 x 0.8 from the flank's inner face",
                   O=np.array([unit(HALF_W + 5.0, KEY_S + a_, KEY_N + b_) for a_, b_ in zip(ds, dn)]),
                   D=np.array([-1.0, 0, 0]), floor=5.0 + WALL - KEY_CBORE_DEPTH, side="far", rule="skin"))
    pr.append(dict(part="shell", name="insert holes, 4.0 x 6.5 from the boss face (blind)",
                   O=np.array([(x, y, -5.0) for x, y in BOSS_XY]), D=Z, floor=5.0 + BOSS_Z0 + INSERT_HOLE_DEPTH,
                   side="near", rule="skin"))
    return pr


def skin_check(asm_tm):
    out = []
    for p in skin_probes():
        tm = asm_tm[p["part"]]
        V, F = np.asarray(tm.vertices), np.asarray(tm.faces)
        t_in, t_out = _first_segment(V, F, p["O"], p["D"], p["floor"] + 25.0)
        at = t_in if p["side"] == "near" else t_out
        ok = np.isfinite(t_in) & np.isfinite(t_out) & (np.abs(at - p["floor"]) < 0.05)
        sk = (t_out - t_in)[ok]
        row = {"part": p["part"], "recess": p["name"], "rule": p["rule"], "samples": int(ok.sum())}
        if ok.any():
            i = int(np.argmin(sk))
            vals, cnt = np.unique(np.round(sk, 2), return_counts=True)
            row.update({"skin_min_mm": round(float(sk[i]), 2),
                        "at": [round(float(v), 1) for v in p["O"][ok][i] + p["D"] * t_in[ok][i]],
                        "skins_mm": {f"{v:.2f}": int(c) for v, c in zip(vals, cnt)}})
            row["ok"] = bool(p["rule"] != "skin" or sk.min() >= SKIN_MIN - 0.005)
        else:
            row["ok"] = False
        out.append(row)
    return out


# ------------------------------------------------------------------ item 2: the wordmark on the layer-1 slice
def mark_layer1(shell_m):
    R = np.column_stack([[1.0, 0, 0], S_DIR, N_OUT])           # local (x, s, −n) → unit, proper
    T0 = np.array([0, TOE_Y, TOE_Z])
    sl = shell_m.transform(np.hstack([R.T, (-R.T @ T0)[:, None]])).slice(-MARK_LAYER1_N)
    x0, x1, s0, s1 = MARK_BOX_X[0] - 3, MARK_BOX_X[1] + 3, MARK_BOX_S[0] - 1.5, MARK_BOX_S[1] + 1.5
    box = mf.CrossSection.square((x1 - x0, s1 - s0)).translate((x0, s0))
    inner = mf.CrossSection.square((x1 - x0 - 1, s1 - s0 - 1)).translate((x0 + 0.5, s0 + 0.5))
    rec = box - sl
    face = box ^ sl
    r = MARK_MIN_FEATURE / 2

    def opened(c):
        return c.offset(-r, mf.JoinType.Round, 2.0, 96).offset(r, mf.JoinType.Round, 2.0, 96)
    # a feature counts if the opening removes more than 0.005 mm² of it (polygon noise is ≤ 0.002)
    thin_rec = [c for c in (rec - opened(rec)).decompose() if c.area() > 0.005]
    slivers = [c for c in ((face - opened(face)) ^ inner).decompose() if c.area() > 0.005]
    counters = []
    for c in rec.decompose():
        for pg in c.to_polygons():
            pg = np.asarray(pg)
            a = 0.5 * np.sum(pg[:, 0] * np.roll(pg[:, 1], -1) - np.roll(pg[:, 0], -1) * pg[:, 1])
            if a < 0:
                counters.append({"area_mm2": round(-a, 2), "at_x_s": [round(float(v), 2) for v in pg.mean(0)]})
    comps = rec.decompose()
    best, _ = webs(comps, MARK_MIN_FEATURE, lambda p: unit(p[0], p[1], 0.0))
    b = rec.bounds()
    ok = not thin_rec and not slivers and all(c["area_mm2"] >= MARK_COUNTER_MIN for c in counters)
    return {"slice_n": MARK_LAYER1_N, "recess_area_mm2": round(rec.area(), 2), "recess_parts": len(comps),
            "recess_x": [round(b[0], 2), round(b[2], 2)], "recess_s": [round(b[1], 2), round(b[3], 2)],
            "recess_features_under_0.6": [{"area_mm2": round(c.area(), 3), "x_s_box": [round(v, 2) for v in c.bounds()]}
                                          for c in thin_rec],
            "face_slivers_under_0.6": [{"area_mm2": round(c.area(), 3), "x_s_box": [round(v, 2) for v in c.bounds()]}
                                       for c in slivers],
            "counters": counters, "narrowest_face_between_parts": best, "ok": bool(ok)}


# ------------------------------------------------------------------ items 3, 5, 7, 8
def slot_area(w, L):
    """Full-round slot, S1: w·L − (1 − π/4)·w² (2.4·L − 1.236 for the 2.4 slots)."""
    return w * L - (1 - math.pi / 4) * w * w


def _series(*a):
    return 1.0 / math.sqrt(sum(1.0 / x ** 2 for x in a))


def vent_areas(walls):
    """Vent areas from the slot lists the geometry is cut from (S1 formula), combined as the spec
    does (§5.2, CHK §7): orifices in series add as 1/A² ; the floor's effective area is shared
    between the hot and cold groups in proportion to their open area."""
    w = SLOT_W
    H = sum(slot_area(w, H_SLOTS_Z[1] - H_SLOTS_Z[0]) for x in H_SLOTS_X if x not in H_SLOTS_SKIP)
    C = (len(C1_X) * slot_area(w, C1_Z[1] - C1_Z[0]) + (len(C2_X) + len(C3_X)) * slot_area(w, C23_Z[1] - C23_Z[0])
         + len(C4_X) * slot_area(w, C4_Z[1] - C4_Z[0]))
    top_n = len(TOP_SLOTS_ROW_Z) * len(TOP_SLOTS_X)
    top = top_n * slot_area(TOP_SLOT_W, TOP_SLOT_L)
    A = sum(slot_area(w, (BAND_A_Y_SHORT if i in BAND_A_SHORT_I else BAND_A_Y)[1] -
                      (BAND_A_Y_SHORT if i in BAND_A_SHORT_I else BAND_A_Y)[0]) for i in range(len(BAND_A_X)))
    b1 = slot_area(w, BAND_B_Y[1] - BAND_B_Y[0])
    blocked = [x for x in BAND_B_X if PORT_BLOCK_X[0] <= x <= PORT_BLOCK_X[1]]
    B_gross, B_open = len(BAND_B_X) * b1, (len(BAND_B_X) - 0.5 * len(blocked)) * b1
    low = len(LOW_X) * slot_area(w, LOW_Y[1] - LOW_Y[0])
    floor_eff = _series(H + C, UNDER_CASE_GAP_AREA)
    hot_floor, cold_floor = floor_eff * H / (H + C), floor_eff * C / (H + C)
    hot_in, hot_out = hot_floor + low, A + B_open
    measured = {f"{p} {wl}": round(sum(c.area() for c in comps), 1) for p, wl, comps, _ in walls}
    r = lambda v: round(v, 0)
    return {
        "method": "slot area w·L − (1 − π/4)·w² (S1); orifices in series combine as 1/A² = Σ 1/Aᵢ² (§5.2); "
                  "band B counts the slots behind the port block at half (the spec's convention)",
        "floor_H": r(H), "floor_C1_C4": r(C), "under_case_gap": UNDER_CASE_GAP_AREA,
        "floor_in_series_with_gap": {"total": r(floor_eff), "hot": r(hot_floor), "cold": r(cold_floor)},
        "rear_low_band": {"slots": len(LOW_X), "area": r(low), "note": "item 1: the slot at x 48.4 is dropped"},
        "band_A": r(A), "band_B": {"slots": len(BAND_B_X), "gross": r(B_gross), "open": r(B_open),
                                   "half_counted_x": blocked},
        "hot_intake": r(hot_in), "hot_exhaust": r(hot_out), "hot_channel_effective": r(_series(hot_in, hot_out)),
        "top_land": {"slots": top_n, "slot_w_L": [TOP_SLOT_W, TOP_SLOT_L], "rows_z": TOP_SLOTS_ROW_Z,
                     "x_centres": [TOP_SLOTS_X[0], TOP_SLOTS_X[-1]], "area": r(top),
                     "note": "item 3: crosswise, three rows in z 4-16, x within ±75"},
        "cold_intake": r(cold_floor), "cold_channel_effective": r(_series(cold_floor, top)),
        "measured_through_area_mm2": measured,
    }


def foam_check(foam_m):
    rows = []
    for c in foam_m.decompose():
        V, _ = m_arrays(c)
        s = np.array([face_sn(v[1], v[2])[0] for v in V])
        x = V[:, 0]
        rows.append({"x": [round(float(x.min()), 2), round(float(x.max()), 2)], "s": [round(float(s.min()), 2), round(float(s.max()), 2)]})
    bottom = [r for r in rows if r["s"][1] < 60]
    top = [r for r in rows if r["s"][0] >= 60]
    ok = all(r["s"][1] <= WIN_IN_S[0] + 1e-6 for r in bottom) and all(r["s"][0] >= WIN_IN_S[1] - 1e-6 for r in top)
    return {"bottom_pads": bottom, "top_pads": top, "window_panel_side_s": list(WIN_IN_S),
            "bottom_margin_to_window": round(WIN_IN_S[0] - max(r["s"][1] for r in bottom), 2),
            "top_margin_to_window": round(min(r["s"][0] for r in top) - WIN_IN_S[1], 2), "ok": bool(ok)}


def pad_check(plate_m, shell_m, plate_openings):
    """Item 5: each P2 pad clears P1 (other than its boss face), P2's through-openings (other than
    its own hole) and every other P2 feature at the pad's height."""
    sl = plate_m.slice(P2_T + P2_PAD_T / 2)
    comps = sl.decompose()
    rows, ok = [], True
    rp = P2_PAD_D / 2
    for x, y in BOSS_XY:
        c = np.array([x, y])
        pad = m_cyl((x, y, P2_T), (x, y, P2_T + P2_PAD_T), P2_PAD_D, 96)
        # the boss face bears on the pad top at z 3.5 (intended); the clearance is to the rest of P1
        # below that plane (flank, floor or top land)
        gap_p1 = float(pad.min_gap(shell_m.trim_by_plane([0, 0, -1.0], -(BOSS_Z0 - 0.05)), 10.0))

        def nearest(cs_list, skip_inside):
            best = (np.inf, None)
            for cs in cs_list:
                b = cs.bounds()
                if skip_inside and b[0] <= x <= b[2] and b[1] <= y <= b[3]:
                    continue
                P = _boundary_points(cs, 0.05)
                d = np.linalg.norm(P - c, axis=1)
                k = int(np.argmin(d))
                if d[k] < best[0]:
                    best = (float(d[k]), P[k])
            return round(best[0] - rp, 2), [round(float(v), 1) for v in best[1]]
        g_open, at_open = nearest(plate_openings, True)
        g_feat, at_feat = nearest(comps, True)
        row = {"pad_xy": [x, y], "to_P1_below_boss_face_mm": round(gap_p1, 2), "boss_face_on_pad_top_z": BOSS_Z0,
               "to_nearest_through_opening_mm": g_open,
               "opening_at": at_open, "to_nearest_P2_feature_at_pad_height_mm": g_feat, "feature_at": at_feat}
        row["ok"] = bool(gap_p1 > 0.05 and g_open > 0.05 and g_feat > 0.05)
        ok &= row["ok"]
        rows.append(row)
    return {"pads": rows, "ok": bool(ok)}


def screw_check(screws_m, shell_tm):
    V, F = np.asarray(shell_tm.vertices), np.asarray(shell_tm.faces)
    lo, hi = np.array(screws_m.bounding_box()).reshape(2, 3)
    O = np.array([(x, y, -5.0) for x, y in BOSS_XY])
    t, _ = raycast(V, F, O, np.array([0, 0, 1.0]))
    hole_end = float((t - 5.0).min())
    tip = float(hi[2])
    return {"screw": f"M3 × {M3_L:g} button head (ISO 7380)", "head_z": [round(float(lo[2]), 2), P2_CBORE_DEPTH],
            "head_below_outer_face": round(float(lo[2]), 2), "under_head_P2": round(P2_T + P2_PAD_T - P2_CBORE_DEPTH, 2),
            "tip_z": round(tip, 2), "insert_hole_end_z": round(hole_end, 2), "tip_short_of_hole_end": round(hole_end - tip, 2),
            "insert_z": [BOSS_Z0, round(BOSS_Z0 + INSERT_L, 2)], "engagement_in_insert": round(tip - BOSS_Z0, 2),
            "ok": bool(tip < hole_end - 0.05)}


def envelope_check(env_m, plate_m):
    v = float((env_m ^ plate_m).volume())
    gap = float(env_m.min_gap(plate_m, 10.0))
    return {"envelope": dict(PSU_ENV), "overlap_with_P2_mm3": round(v, 4), "clearance_to_P2_mm": round(gap, 2),
            "ok": bool(v < 1e-6 and gap > 0.0)}


# ------------------------------------------------------------------ sections
def _chain(segs, tol=1e-4):
    """Chain 2D segments into polylines (closed where possible)."""
    key = lambda p: (round(p[0] / tol), round(p[1] / tol))
    from collections import defaultdict
    adj = defaultdict(list)
    for i, (a, b) in enumerate(segs):
        adj[key(a)].append((i, 0))
        adj[key(b)].append((i, 1))
    used = np.zeros(len(segs), bool)
    loops = []
    for i in range(len(segs)):
        if used[i]:
            continue
        used[i] = True
        line = [segs[i][0], segs[i][1]]
        while True:
            nxt = [(j, e) for j, e in adj[key(line[-1])] if not used[j]]
            if not nxt:
                break
            j, e = nxt[0]
            used[j] = True
            line.append(segs[j][1 - e])
        loops.append(np.array(line))
    return loops


def section_svg(asm_tm, colours, plane, title, path):
    """plane: ('x', value) or ('y', value)."""
    axis, val = plane
    normal = {"x": [1, 0, 0], "y": [0, 1, 0]}[axis]
    origin = np.array(normal, float) * val
    polys = []
    for name, tm in asm_tm.items():
        try:
            segs = trimesh.intersections.mesh_plane(tm, normal, origin)
        except Exception:
            continue
        if len(segs) == 0:
            continue
        if axis == "x":
            s2 = segs[:, :, [2, 1]] * np.array([1, -1])        # z right, y up
        else:
            s2 = segs[:, :, [0, 2]]                             # x right, z down (front at the bottom)
        polys.append((name, _chain([tuple(map(tuple, s)) for s in s2])))
    allp = np.vstack([np.vstack(L) for _, Ls in polys for L in Ls]) if polys else np.zeros((1, 2))
    lo, hi = allp.min(0) - 8, allp.max(0) + 8
    sc = 5.0
    W, H = (hi - lo) * sc
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W:.0f}" height="{H + 60:.0f}" '
           f'viewBox="{lo[0]:.2f} {lo[1] - 12:.2f} {hi[0] - lo[0]:.2f} {hi[1] - lo[1] + 12:.2f}" '
           f'font-family="Helvetica, Arial, sans-serif">',
           f'<rect x="{lo[0]}" y="{lo[1] - 12}" width="{hi[0] - lo[0]}" height="{hi[1] - lo[1] + 12}" fill="#fbfaf6"/>',
           f'<text x="{lo[0] + 2}" y="{lo[1] - 5}" font-size="4">{title}</text>']
    for name, Ls in polys:
        d = " ".join("M" + " L".join(f"{p[0]:.3f},{p[1]:.3f}" for p in L) + (" Z" if np.allclose(L[0], L[-1], atol=1e-3) else "")
                     for L in Ls)
        out.append(f'<path d="{d}" fill="{colours.get(name, "#999")}" fill-opacity="0.75" fill-rule="evenodd" '
                   f'stroke="#222" stroke-width="0.08"><title>{name}</title></path>')
    out.append("</svg>")
    open(path, "w").write("\n".join(out))
    return [n for n, _ in polys]
