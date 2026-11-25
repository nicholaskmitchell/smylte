"""The printed parts P1–P6 in build123d, in assembly position (unit frame) except P5 and P6,
which are built in bed coordinates."""
import json
import math
import os
import numpy as np
from build123d import (Plane, Location, Pos, Rot, Box, Cylinder, Cone, Torus, Polygon, Rectangle,
                       RectangleRounded, extrude, loft, fillet, chamfer, offset, Kind, Axis,
                       GeomType)

from params import *  # noqa: F401,F403  (every number lives in params.py)
from geom import (FACE, S_DIR, N_DIR, N_OUT, unit, face_box, box, prism_x, prism_sn, zcyl, slot,
                  compound, cut_all)

HERE = os.path.dirname(os.path.abspath(__file__))


def _z_on_face_line(n, y):
    """z of the point at face depth n and height y (§1.1 inverse)."""
    return TOE_Z - (n + SIN * (y - TOE_Y)) / COS


def _near(e, y, z, tol=0.5):
    c = e.center()
    return abs(c.Y - y) < tol and abs(c.Z - z) < tol


def _prism_y(pts_xz, y0, y1):
    pl = Plane(origin=(0, y0, 0), x_dir=(1, 0, 0), z_dir=(0, -1, 0))
    return extrude(pl * Polygon(*pts_xz, align=None), amount=y1 - y0, dir=(0, 1, 0))


# =================================================================== P1 shell (§2.1)
def outer_prism():
    prof = [(TOE_Z, TOE_Y), (TOP_LAND_Z, TOP_Y), (0, TOP_Y), (0, TOE_Y)]
    return prism_x(prof, -HALF_W, HALF_W)


def _shell_body():
    o = outer_prism()
    # face perimeter (the bed edge): 0.4 × 45° on the toe and the two side edges
    toe = [e for e in o.edges().filter_by(Axis.X) if _near(e, TOE_Y, TOE_Z)]
    sides = [e for e in o.edges() if abs(abs(e.center().X) - HALF_W) < 0.01
             and abs(abs(e.tangent_at(0.5).Y) - COS) < 1e-3 and e.center().Z > 20]
    o = chamfer(toe + sides, FACE_CHAMFER)
    # face to top-land edge R 1.0
    o = fillet([e for e in o.edges().filter_by(Axis.X) if _near(e, TOP_Y, TOP_LAND_Z)], TOP_EDGE_R)
    # rear edges R 0.5
    o = fillet([e for e in o.edges() if abs(e.center().Z) < 0.01], REAR_EDGE_R)
    return o


def _boss(xc, yc):
    upper = yc > 60
    half = BOSS_CONE_HALF_UPPER if upper else BOSS_CONE_HALF_LOWER
    r = BOSS_D / 2
    t = math.tan(math.radians(half))
    apex = BOSS_Z1 + r / t
    cyl = zcyl(xc, yc, BOSS_Z0, BOSS_Z1, BOSS_D)
    cone = Pos(xc, yc, (BOSS_Z1 + apex) / 2) * Cone(r, 0, apex - BOSS_Z1)
    # F2: fill the full 8 mm width solid from the boss to the floor or the top land
    sil = [(xc - r, BOSS_Z0), (xc - r, BOSS_Z1), (xc, apex), (xc + r, BOSS_Z1), (xc + r, BOSS_Z0)]
    fill = _prism_y(sil, yc, LAND_UNDER + 0.5) if upper else _prism_y(sil, FLOOR_TOP - 0.5, yc)
    # §2.1 2.0 web to the flank, its free edge sloped at the cone's half-angle
    sx = 1 if xc > 0 else -1
    xf = sx * (FLANK_IN + 0.5)
    web_pts = [(xc, BOSS_Z0), (xc, apex), (xf, apex - abs(xf - xc) / t), (xf, BOSS_Z0)]
    web = _prism_y(web_pts, yc - BOSS_WEB_T / 2, yc + BOSS_WEB_T / 2)
    return cyl + cone + fill + web


def mark_loops():
    """Rev D's `mark` outline placed in the §2.1 box: list of (kind, [(x, s), ...])."""
    d = json.load(open(os.path.join(HERE, "mark_outline.json")))
    loops = [np.array(L["uv"]) for L in d["loops"]]
    allp = np.vstack(loops)
    c_src = (allp.min(0) + allp.max(0)) / 2
    c_dst = np.array([(MARK_BOX_X[0] + MARK_BOX_X[1]) / 2, (MARK_BOX_S[0] + MARK_BOX_S[1]) / 2])
    out = []
    for L, meta in zip(loops, d["loops"]):
        out.append((meta["kind"], meta.get("group"), [tuple(p) for p in (L - c_src + c_dst)]))
    return out


def mark_sections():
    """Item 2, an FDM cut (reading B): the outer letter loops grown by MARK_GROW, the counters kept as
    they are, then the recess closed (+0.3, −0.3) and opened (−0.3, +0.3). The period is left as it is.
    Returns (letters, period) as manifold3d CrossSections in (x, s)."""
    import manifold3d as mf
    outers, holes, period = [], [], []
    for kind, group, pts in mark_loops():
        cs = mf.CrossSection([np.asarray(pts)], mf.FillRule.NonZero)
        (holes if kind == "hole" else period if kind == "period" else outers).append(cs)

    def U(cs):
        return mf.CrossSection.batch_boolean(cs, mf.OpType.Add)

    def off(c, d):
        return c.offset(d, mf.JoinType.Round, 2.0, 64)
    letters = U([off(c, MARK_GROW) for c in outers]) - U(holes)
    letters = off(off(letters, MARK_CLOSE), -MARK_CLOSE)
    letters = off(off(letters, -MARK_OPEN), MARK_OPEN)
    return letters.simplify(0.001), U(period)


def _cs_faces(cs, pl):
    """build123d faces (with holes) of a CrossSection, on plane pl."""
    out = []
    for comp in cs.decompose():
        polys = [np.asarray(p) for p in comp.to_polygons()]
        area = [0.5 * np.sum(p[:, 0] * np.roll(p[:, 1], -1) - np.roll(p[:, 0], -1) * p[:, 1]) for p in polys]
        f = None
        for p, a in sorted(zip(polys, area), key=lambda t: -t[1]):
            g = pl * Polygon(*[tuple(q) for q in p], align=None)
            f = g if f is None else f - g
        out.append(f)
    return out


def mark_faces(n_floor):
    """Faces of the mark at face depth n_floor: (letters, period)."""
    pl = FACE.offset(-n_floor)
    letters, period = mark_sections()
    return _cs_faces(letters, pl), _cs_faces(period, pl)


def build_shell():
    body = _shell_body()
    raw = outer_prism()
    # cavity, open at the back
    zf, zt = _z_on_face_line(WALL, FLOOR_TOP), _z_on_face_line(WALL, LAND_UNDER)
    cav = prism_x([(zf, FLOOR_TOP), (zt, LAND_UNDER), (-1, LAND_UNDER), (-1, FLOOR_TOP)], -FLANK_IN, FLANK_IN)
    body = body - cav
    body = body - box(-REBATE_X, REBATE_X, REBATE_Y[0], REBATE_Y[1], -1, REBATE_Z)   # F1 rebates z 0–2.0

    adds = []
    # ledge rib, with the tail notch
    adds += [face_box(-FLANK_IN - 0.5, NOTCH_X[0], RIB_S[0], RIB_S[1], RIB_N[0] - 0.5, RIB_N[1]),
             face_box(NOTCH_X[1], FLANK_IN + 0.5, RIB_S[0], RIB_S[1], RIB_N[0] - 0.5, RIB_N[1])]
    # toe blocks and lips
    for sx in (-1, 1):
        x0, x1 = sorted((sx * TOE_BLOCK_X[0], sx * (TOE_BLOCK_X[1] + 0.5)))
        adds.append(face_box(x0, x1, -4.0, POCKET_S[0], 0.5, TOE_BLOCK_N) & raw)
        lx0, lx1 = sorted((sx * LIP_X[0], sx * LIP_X[1]))
        lip = [(LIP_S[0] - 0.5, LIP_N[0]), (LIP_S[1], LIP_N[0]), (LIP_S[1], LIP_N[1] - LIP_CHAMFER),
               (LIP_S[1] - LIP_CHAMFER, LIP_N[1]), (LIP_S[0] - 0.5, LIP_N[1])]
        adds.append(prism_sn(lip, lx0, lx1))
    # top corner block
    adds.append(face_box(-FLANK_IN - 0.5, FLANK_IN + 0.5, CORNER_S0, FACE_L + 4.0, CORNER_N[0] - 0.5, CORNER_N[1]) & raw)
    # screw bosses
    adds += [_boss(x, y) for x, y in BOSS_XY]
    # ballast bays: side ribs tapered to the floor at z 52 (F3), front stops with ramps
    zt_rib = BAY_RIB_Z[1] - (BAY_RIB_Y[1] - FLOOR_TOP) / math.tan(math.radians(BAY_RIB_TAPER))
    rib = [(BAY_RIB_Z[0], FLOOR_TOP - 0.5), (BAY_RIB_Z[0], BAY_RIB_Y[1]), (zt_rib, BAY_RIB_Y[1]),
           (BAY_RIB_Z[1], FLOOR_TOP), (BAY_RIB_Z[1], FLOOR_TOP - 0.5)]
    adds += [prism_x(rib, a, b) for a, b in RIB_XS]
    stop = [(STOP_Z_REAR, FLOOR_TOP - 0.5), (STOP_Z_REAR, STOP_TOP_Y), (STOP_Z_TOE, FLOOR_TOP),
            (STOP_Z_TOE, FLOOR_TOP - 0.5)]
    adds += [prism_x(stop, a, b) for a, b in STOP_XS]
    for a in adds:
        body = body + a

    cuts = []
    # window with 45° bevel
    smid = (WIN_OUT_S[0] + WIN_OUT_S[1]) / 2
    w_o, h_o = WIN_OUT_X[1] - WIN_OUT_X[0], WIN_OUT_S[1] - WIN_OUT_S[0]
    w_i, h_i = WIN_IN_X[1] - WIN_IN_X[0], WIN_IN_S[1] - WIN_IN_S[0]
    f_front = FACE * Pos(0, smid) * RectangleRounded(w_o, h_o, WIN_OUT_R)
    f_bevel = FACE.offset(-WIN_BEVEL_N) * Pos(0, smid) * RectangleRounded(w_i, h_i, WIN_IN_R)
    cuts.append(loft([f_front, f_bevel]))
    cuts.append(extrude(FACE.offset(0.5) * Pos(0, smid) * RectangleRounded(w_o, h_o, WIN_OUT_R), amount=0.5, dir=tuple(N_DIR)))
    cuts.append(extrude(FACE.offset(-WIN_BEVEL_N + 0.01) * Pos(0, smid) * RectangleRounded(w_i, h_i, WIN_IN_R),
                        amount=1.6, dir=tuple(N_DIR)))
    # key cutout and counterbore
    kc = face_box(FLANK_IN - 0.5, HALF_W + 0.5, KEY_S - KEY_CUT / 2, KEY_S + KEY_CUT / 2,
                  KEY_N - KEY_CUT / 2, KEY_N + KEY_CUT / 2)
    kc = fillet(kc.edges().filter_by(Axis.X), KEY_CUT_R)
    cuts.append(kc)
    cuts.append(face_box(FLANK_IN - 0.5, FLANK_IN + KEY_CBORE_DEPTH, KEY_S - KEY_CBORE / 2, KEY_S + KEY_CBORE / 2,
                         KEY_N - KEY_CBORE / 2, KEY_N + KEY_CBORE / 2))
    # insert holes, from the boss face at z 3.5 (item 5), ending at z 10.0
    cuts += [zcyl(x, y, BOSS_Z0 - 0.5, BOSS_Z0 + INSERT_HOLE_DEPTH, INSERT_HOLE_D) for x, y in BOSS_XY]
    # floor slots
    def floor_slot(x, z0, z1):
        return slot((x, TOE_Y - 0.5, (z0 + z1) / 2), (0, 0, 1), (0, 1, 0), z1 - z0, SLOT_W, 0, WALL + 0.6)
    cuts += [floor_slot(x, *H_SLOTS_Z) for x in H_SLOTS_X if x not in H_SLOTS_SKIP]
    cuts += [floor_slot(x, *C1_Z) for x in C1_X]
    cuts += [floor_slot(x, *C23_Z) for x in C2_X + C3_X]
    cuts += [floor_slot(x, *C4_Z) for x in C4_X]
    # top-land slots, crosswise (item 3): long axis along x, so their upper edges print as bridges
    cuts += [slot((x, LAND_UNDER - 0.23, z), (1, 0, 0), (0, 1, 0), TOP_SLOT_L, TOP_SLOT_W, 0, WALL + 0.6)
             for z in TOP_SLOTS_ROW_Z for x in TOP_SLOTS_X]
    # foot locator rings
    cuts += [Pos(x, TOE_Y + FOOT_RING_DEPTH - 0.35, z) * Rot(90, 0, 0) * Cylinder(FOOT_RING_D / 2, 0.7)
             for x, z in FOOT_XZ]
    # wordmark, 0.4 deep
    letters, period = mark_faces(MARK_DEPTH)
    cuts += [extrude(f, amount=MARK_DEPTH + 0.3, dir=tuple(N_OUT)) for f in letters + period]
    return cut_all(body, cuts)


# =================================================================== P2 rear plate (§2.2)
def roof_y_hot(z):
    (z0, y0), (z1, y1) = ROOF_P0, ROOF_P1
    return y0 + (z - z0) * (y1 - y0) / (z1 - z0)


def build_rear_plate():
    ymid = (P2_Y[0] + P2_Y[1]) / 2
    plate = extrude(Plane.XY * Pos(0, ymid) * RectangleRounded(2 * P2_X, P2_Y[1] - P2_Y[0], P2_CORNER_R), amount=P2_T)
    cuts = []

    def vslot(x, y0, y1, z1=P2_T):
        """full-round slot cut from z −1 up to z1 (through by default)"""
        return slot((x, (y0 + y1) / 2, -1), (0, 1, 0), (0, 0, 1), y1 - y0, SLOT_W, 0, z1 + 1.0)
    for i, x in enumerate(BAND_A_X):
        cuts.append(vslot(x, *(BAND_A_Y_SHORT if i in BAND_A_SHORT_I else BAND_A_Y)))
    # item 4: 0.4 blind recesses from the outer face, so band A's shortened slots read 14 long from
    # behind and band B reads unbroken across the standoff island. No new through-slot.
    cuts += [vslot(x, *BAND_A_RECESS_Y, OUTER_RECESS_DEPTH) for i, x in enumerate(BAND_A_X) if i in BAND_A_SHORT_I]
    cuts += [vslot(x, *BAND_B_Y, OUTER_RECESS_DEPTH) for x in BAND_B_RECESS_X]
    cuts += [vslot(x, *BAND_B_Y) for x in BAND_B_X]
    cuts += [vslot(x, *LOW_Y) for x in LOW_X]
    cx, cy, w, h, r = USBC_WIN
    cuts.append(extrude(Plane.XY.offset(-1) * Pos(cx, cy) * RectangleRounded(w, h, r), amount=P2_T + 2))
    cx, cy, w, h, r = USBA_CUT
    cuts.append(extrude(Plane.XY.offset(-1) * Pos(cx, cy) * RectangleRounded(w, h, r), amount=P2_T + 2))
    cuts += [zcyl(x, y, -1, 3, P2_SCREW_D) for x, y in USBA_EARS]
    for (x0, x1), (y0, y1) in (RECESS_HEADER, RECESS_J2):
        cuts.append(box(x0, x1, y0, y1, P2_T - RECESS_DEPTH, P2_T + 0.5))
    plate = cut_all(plate, cuts)

    adds = []
    # Pi standoffs, R 1.5 base fillet; the base ring starts at z 1.0 so the union over the header
    # recess is clean (S9)
    rr = STANDOFF_D / 2 + STANDOFF_FILLET
    for x, y in STANDOFF_XY:
        core = zcyl(x, y, P2_T - RECESS_DEPTH, STANDOFF_TOP, STANDOFF_D)
        ring = zcyl(x, y, P2_T - RECESS_DEPTH, P2_T + STANDOFF_FILLET, 2 * rr) - \
            (Pos(x, y, P2_T + STANDOFF_FILLET) * Torus(rr, STANDOFF_FILLET))
        adds.append(core + ring)
    # duct roof
    dy = ROOF_T * math.hypot(ROOF_P1[0] - ROOF_P0[0], ROOF_P1[1] - ROOF_P0[1]) / (ROOF_P1[0] - ROOF_P0[0])
    zr0 = P2_T - 1.0
    roof = [(zr0, roof_y_hot(zr0)), (ROOF_P1[0], ROOF_P1[1]), (ROOF_P1[0], ROOF_P1[1] + dy), (zr0, roof_y_hot(zr0) + dy)]
    adds.append(prism_x(roof, *ROOF_X))
    # backer posts: tip plane parallel to the backer's rear face, POST_PRELOAD into it (S6)
    for x, y in POST_XY:
        p = zcyl(x, y, P2_T - 0.5, 30.0, POST_D) & face_box(-200, 200, -100, 300, BACKER_N[1] - POST_PRELOAD, 400)
        tip = [e for e in p.edges() if e.center().Z > 10]
        p = fillet(tip, POST_TIP_R)
        adds.append(p)
    # S3 USB-C adapter saddle: SET FROM THE ADAPTER YOU BUY
    adds += saddle()
    # item 5: a pad on the inner face at each screw hole; the boss faces of P1 bear on it at z 3.5
    adds += [zcyl(x, y, P2_T - 0.5, P2_T + P2_PAD_T, P2_PAD_D) for x, y in BOSS_XY]
    for a in adds:
        plate = plate + a
    plate = cut_all(plate, [zcyl(x, y, STANDOFF_TOP - PILOT_DEPTH, STANDOFF_TOP + 1, PILOT_D) for x, y in STANDOFF_XY] +
                    [box(ROOF_NOTCH_X[0], ROOF_NOTCH_X[1], 60.0, ROOF_NOTCH_Y, 2.5, 30.0)] +
                    # screw holes through plate and pad, counterbored from outside (1.7 left under the head)
                    [zcyl(x, y, -1, P2_T + P2_PAD_T + 1, P2_SCREW_D) for x, y in BOSS_XY] +
                    [zcyl(x, y, -1, P2_CBORE_DEPTH, P2_CBORE_D) for x, y in BOSS_XY])
    return plate


def saddle():
    """S3: cheeks either side of the L-adapter, a rear bar behind its neck (cable tug) and a front
    wall ahead of its body (plug insertion). Sized from the ADP allowance in params.py."""
    g, t = SADDLE_GAP, SADDLE_WALL
    zf0 = ADP["rec_z"][1] + g                 # front wall
    zf1 = zf0 + t
    zb1 = ADP["neck_z"][0] - g                # rear bar's front face
    yb0 = SADDLE_BAR_Y0                       # item 7: rear bar's underside flush with the window top
    z0 = P2_T - RECESS_DEPTH
    # item 7 (a): below y 17.5 the cheeks exist only ahead of the receptacle's rear face, under the
    # support chamfer z = 31.5 − y (through z 14.5, y 17.0), so the PSU plug envelope passes them
    zc = SADDLE_CHEEK_CHAMFER
    cheek = [(z0, SADDLE_BAR_Y0), (z0, SADDLE_TOP_Y), (zf1, SADDLE_TOP_Y), (zf1, SADDLE_LOW_Y),
             (zc - SADDLE_LOW_Y, SADDLE_LOW_Y), (zc - SADDLE_BAR_Y0, SADDLE_BAR_Y0)]
    bar = [(z0, yb0), (z0, SADDLE_TOP_Y), (zb1, SADDLE_TOP_Y), (zb1, yb0)]
    front = [(zf0, SADDLE_LOW_Y), (zf1, SADDLE_LOW_Y), (zf1, SADDLE_TOP_Y), (zf0, SADDLE_TOP_Y)]
    xi0, xi1 = SADDLE_CHEEK_X[0][1], SADDLE_CHEEK_X[1][0]
    out = [prism_x(cheek, a - 0.0, b) for a, b in SADDLE_CHEEK_X]
    out += [prism_x(bar, xi0 - 0.3, xi1 + 0.3), prism_x(front, xi0 - 0.3, xi1 + 0.3)]
    return out


# =================================================================== P3 backer (§2.3)
def build_backer():
    smid = (BACKER_S[0] + BACKER_S[1]) / 2
    pl = FACE.offset(-BACKER_N[1])
    b = extrude(pl * Pos(0, smid) * RectangleRounded(2 * BACKER_X, BACKER_S[1] - BACKER_S[0], BACKER_CORNER_R),
                amount=BACKER_N[1] - BACKER_N[0], dir=tuple(N_OUT))
    # R 1.0 on the bottom rear edge in the tail zone
    cs, cn, r = BACKER_S[0] + BACKER_TAIL_R, BACKER_N[1] - BACKER_TAIL_R, BACKER_TAIL_R
    arc = [(cs + r * math.cos(math.radians(a)), cn + r * math.sin(math.radians(a))) for a in np.linspace(180, 90, 19)]
    tool = [(BACKER_S[0] - 0.1, cn)] + arc + [(cs, BACKER_N[1] + 0.1), (BACKER_S[0] - 0.1, BACKER_N[1] + 0.1)]
    b = b - prism_sn(tool, *NOTCH_X)
    for x, s in PAD_XS:
        b = b + face_box(x - PAD / 2, x + PAD / 2, s - PAD / 2, s + PAD / 2, PAD_N[0] - 0.1, PAD_N[1])
    cuts = [face_box(x0, x1, SWITCH_POCKET_S[0], SWITCH_POCKET_S[1], BACKER_N[1] - SWITCH_POCKET_DEPTH, BACKER_N[1] + 0.1)
            for x0, x1 in SWITCH_POCKETS_X]
    (gx0, gx1), (gs0, gs1), gr = GH_WIN
    cuts.append(extrude(FACE.offset(-BACKER_N[0] + 0.2) * Pos((gx0 + gx1) / 2, (gs0 + gs1) / 2) *
                        RectangleRounded(gx1 - gx0, gs1 - gs0, gr), amount=3.0, dir=tuple(N_DIR)))
    return cut_all(b, cuts)


# =================================================================== P4 key carrier (§2.4, F4, F5)
# key-local frame: (u, v, w) = (Δs, Δn, 85.2 − x)
KEY_PLANE = Plane(origin=tuple(unit(P4_X[1], KEY_S, KEY_N)), x_dir=tuple(S_DIR), z_dir=(-1, 0, 0))


def sock_to_key(us, vs):
    """Socket drawing frame (u along the long axis, v across, sleeve A at 0,0) to (Δs, Δn)."""
    return vs + SLEEVE_A[0], us + SLEEVE_A[1]


def pilot_positions():
    (ua0, _), (va0, va1) = SOCKET_TABS[0]
    (_, ub1), (vb0, vb1) = SOCKET_TABS[1]
    a = sock_to_key(ua0 - PILOT_BEYOND_TAB, (va0 + va1) / 2)
    b = sock_to_key(ub1 + PILOT_BEYOND_TAB, (vb0 + vb1) / 2)
    return a, b


def socket_outline(grow=0.0):
    """Kailh CPG135001S30 outline (body plus both tabs) in (Δs, Δn), grown by `grow` with round
    corners; one polygon."""
    import manifold3d as mf
    cs = mf.CrossSection([np.array([sock_to_key(u, v) for u, v in SOCKET_BODY])], mf.FillRule.NonZero)
    for (u0, u1), (v0, v1) in SOCKET_TABS:
        r = [sock_to_key(u, v) for u, v in ((u0, v0), (u1, v0), (u1, v1), (u0, v1))]
        cs = cs + mf.CrossSection([np.array(r)], mf.FillRule.NonZero)
    if grow:
        cs = cs.offset(grow, mf.JoinType.Round, 2.0, 48)
    polys = cs.to_polygons()
    assert len(polys) == 1, "socket outline is not one polygon"
    return [tuple(p) for p in np.asarray(polys[0])]


def groove_lines():
    """Item 6: each wire groove runs straight along its tab's centreline from P4's −s edge into the
    socket pocket. Returns, for tabs A and B, (Δn of the centreline, Δs where the groove meets the
    grown pocket outline, (Δs0, Δs1) of the tab)."""
    poly = np.array(socket_outline(P4_POCKET_GROW))
    out = []
    for (u0, u1), (v0, v1) in SOCKET_TABS:
        dn = sock_to_key((u0 + u1) / 2, 0.0)[1]
        xs = [a[0] + (dn - a[1]) * (b[0] - a[0]) / (b[1] - a[1])
              for a, b in zip(poly, np.roll(poly, -1, 0)) if (a[1] - dn) * (b[1] - dn) < 0]
        out.append((dn, min(xs), tuple(sorted(sock_to_key(u0, v)[0] for v in (v0, v1)))))
    return out


def build_key_carrier():
    K = KEY_PLANE
    T = P4_X[1] - P4_X[0]
    s0, s1 = P4_S[0] - KEY_S, P4_S[1] - KEY_S
    n0, n1 = P4_N[0] - KEY_N, P4_N[1] - KEY_N
    c = K.location * Pos((s0 + s1) / 2, (n0 + n1) / 2, T / 2) * Box(s1 - s0, n1 - n0, T)

    def hole(u, v, d, w0=-1, w1=T + 1):
        return K.location * Pos(u, v, (w0 + w1) / 2) * Cylinder(d / 2, w1 - w0)
    cuts = [hole(0, 0, P4_CENTRE_D), hole(0, -P4_LOC_DN, P4_LOC_D), hole(0, P4_LOC_DN, P4_LOC_D),
            hole(*SLEEVE_A, P4_SLEEVE_D), hole(*SLEEVE_B, P4_SLEEVE_D)]
    pl = K.offset(T - P4_POCKET_DEPTH)
    grown = pl * Polygon(*socket_outline(P4_POCKET_GROW), align=None)
    cuts.append(extrude(grown, amount=P4_POCKET_DEPTH + 0.5, dir=(-1, 0, 0)))
    for (pu, pv) in pilot_positions():
        cuts.append(hole(pu, pv, PILOT_KEY_D, T - PILOT_KEY_DEPTH, T + 1))
    # item 6: grooves ramp from GROOVE_D deep at the −s edge to the pocket floor where they meet it
    for dn, sp, _ in groove_lines():
        prof = [(s0 - 0.5, T - GROOVE_D), (s0, T - GROOVE_D), (sp, T - P4_POCKET_DEPTH),
                (sp + 0.3, T - P4_POCKET_DEPTH), (sp + 0.3, T + 0.5), (s0 - 0.5, T + 0.5)]
        g = extrude(Plane.XZ.offset(-(dn - GROOVE_W / 2)) * Polygon(*prof, align=None), amount=GROOVE_W, dir=(0, 1, 0))
        cuts.append(K.location * g)
    return cut_all(c, cuts)


# =================================================================== P6 key shoe (F4), bed coordinates
def build_shoe():
    """Local (a, b, t): a along the socket's long axis, pilot at a = 0, the socket toward −a;
    plate t 0–1 on the bed, nose t 1–2 up (in use the nose points into the pocket)."""
    plate = box(-SHOE_L_IN, SHOE_L_OUT, -SHOE_W / 2, SHOE_W / 2, 0, SHOE_T)
    nose = box(-SHOE_L_IN, -SHOE_NOSE_FROM, -SHOE_NOSE_W / 2, SHOE_NOSE_W / 2, SHOE_T - 0.01, SHOE_T + SHOE_NOSE_H)
    return (plate + nose) - zcyl(0, 0, -1, 3, SHOE_HOLE_D)


def shoe_to_unit(i):
    """4×4 matrix placing shoe i (0 = sleeve A side, 1 = B side) on P4 in the unit frame."""
    (sa, na), (sb, nb) = pilot_positions()
    # (a, b, t) → (Δs, Δn, w); w = 85.2 − x, x = 81.0 + t for the head side at x 81.0
    x_head = P4_X[0] - SHOE_T
    if i == 0:
        R = np.array([[0, -1, 0], [-1, 0, 0], [0, 0, -1]], float)
        t = np.array([sa, na, P4_X[1] - x_head])
    else:
        R = np.array([[0, 1, 0], [1, 0, 0], [0, 0, -1]], float)
        t = np.array([sb, nb, P4_X[1] - x_head])
    K = np.column_stack([S_DIR, N_DIR, [-1, 0, 0]])
    o = unit(P4_X[1], KEY_S, KEY_N)
    M = np.eye(4)
    M[:3, :3] = K @ R
    M[:3, 3] = K @ t + o
    return M


# =================================================================== P5 fit gauge (§8, FG), bed coordinates
# bed frame: X = x, Y = −(gauge s), Z = n (face band on the bed)
def build_gauge():
    def gbox(x0, x1, s0, s1, z0, z1):
        return box(x0, x1, -s1, -s0, z0, z1)
    band = gbox(-HALF_W, HALF_W, 0, GAUGE_L, 0, GAUGE_BAND_T)
    smid = -(GAUGE_WIN_S[0] + GAUGE_WIN_S[1]) / 2
    w, h = GAUGE_WIN_X[1] - GAUGE_WIN_X[0], GAUGE_WIN_S[1] - GAUGE_WIN_S[0]
    f0 = Plane.XY * Pos(0, smid) * RectangleRounded(w, h, GAUGE_WIN_R)
    f1 = Plane.XY.offset(GAUGE_BAND_T) * Pos(0, smid) * RectangleRounded(w - 2 * GAUGE_BAND_T, h - 2 * GAUGE_BAND_T,
                                                                          GAUGE_WIN_R - GAUGE_BAND_T)
    win = loft([f0, f1]) + extrude(Plane.XY.offset(-0.5) * Pos(0, smid) * RectangleRounded(w, h, GAUGE_WIN_R), amount=0.51) \
        + extrude(Plane.XY.offset(GAUGE_BAND_T - 0.01) * Pos(0, smid) *
                  RectangleRounded(w - 2 * GAUGE_BAND_T, h - 2 * GAUGE_BAND_T, GAUGE_WIN_R - GAUGE_BAND_T), amount=0.5)
    band = band - win
    walls = gbox(-HALF_W, HALF_W, 0, GAUGE_L, GAUGE_WALL_N[0] - 0.01, GAUGE_WALL_N[1]) - \
        gbox(-GAUGE_POCKET_X, GAUGE_POCKET_X, GAUGE_POCKET_S[0], GAUGE_POCKET_S[1], 0, 5)
    g = band + walls
    (ts0, ts1), tx = TAB_MINUS
    g = g + gbox(tx, GAUGE_POCKET_X + 0.1, ts0, ts1, GAUGE_WALL_N[0] - 0.01, GAUGE_WALL_N[1])
    (ts0, ts1), tx = TAB_PLUS
    g = g - gbox(GAUGE_POCKET_X - 0.1, tx, ts0, ts1, GAUGE_WALL_N[0], GAUGE_WALL_N[1] + 1)
    return g


def build_choc_coupon():
    c = CHOC_COUPON
    x0, sg = COUPON_CHOC_AT
    y0 = -sg - c["T"] / 2                     # wall Y y0..y0+T, foot on the +Y (inner) side
    wall = box(x0 - c["L"] / 2, x0 + c["L"] / 2, y0, y0 + c["T"], 0, c["H"])
    foot = box(x0 - c["L"] / 2, x0 + c["L"] / 2, y0 + c["T"] - 0.01, y0 + c["T"] + c["foot_w"], 0, c["foot_t"])
    cut = box(x0 - KEY_CUT / 2, x0 + KEY_CUT / 2, y0 - 1, y0 + c["T"] + 1, c["cut_z"] - KEY_CUT / 2, c["cut_z"] + KEY_CUT / 2)
    cut = fillet(cut.edges().filter_by(Axis.Y), KEY_CUT_R)
    cb = box(x0 - KEY_CBORE / 2, x0 + KEY_CBORE / 2, y0 + c["T"] - KEY_CBORE_DEPTH, y0 + c["T"] + 1,
             c["cut_z"] - KEY_CBORE / 2, c["cut_z"] + KEY_CBORE / 2)
    return cut_all(wall + foot, [cut, cb])


def build_vent_coupon():
    """Item 3: the top land's crosswise-slot bridge, proved on its own coupon P5d. A 2.0 wall leaning
    20° toward −Y as it rises (as the top land does, face down), on a 1.2 foot, with one slot cut
    normal to the wall."""
    c = VENT_COUPON
    x0, sg = COUPON_VENT_AT
    sn, cs = math.sin(math.radians(c["lean"])), math.cos(math.radians(c["lean"]))
    zt = c["H"] * cs                          # H measured along the wall
    ht = zt * sn / cs
    tw = c["T"] / cs                          # horizontal thickness
    y0 = -sg + (ht - tw) / 2                  # footprint centred on gauge s = sg
    prof = [(0.0, y0), (0.0, y0 + tw), (zt, y0 + tw - ht), (zt, y0 - ht)]
    pl = Plane(origin=(x0 - c["L"] / 2, 0, 0), x_dir=(0, 1, 0), z_dir=(1, 0, 0))
    wall = extrude(pl * Polygon(*[(y, z) for z, y in prof], align=None), amount=c["L"])
    foot = box(x0 - c["L"] / 2, x0 + c["L"] / 2, -sg - c["foot_w"] / 2, -sg + c["foot_w"] / 2, 0, c["foot_t"])
    up = np.array([0.0, -sn, cs])             # along the wall, rising
    nrm = np.array([0.0, cs, sn])             # normal to the wall
    mid = np.array([x0, y0 + tw / 2, 0.0]) + up * (c["H"] / 2)
    return (wall + foot) - slot(tuple(mid), (1, 0, 0), tuple(nrm), TOP_SLOT_L, TOP_SLOT_W, -c["T"], c["T"])


def build_usbc_coupon():
    c = USBC_COUPON
    x0, sg = COUPON_USBC_AT
    p = box(x0 - c["L"] / 2, x0 + c["L"] / 2, -sg - c["W"] / 2, -sg + c["W"] / 2, 0, c["T"])
    _, _, w, h, r = USBC_WIN
    return p - extrude(Plane.XY.offset(-1) * Pos(x0, -sg) * RectangleRounded(w, h, r), amount=c["T"] + 2)
