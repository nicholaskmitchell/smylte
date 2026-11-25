"""Simple, recognisable proxies for the bought parts, in the unit frame (manifold3d solids).
Sizes marked ALW in params.py are allowances, not measurements."""
import math
import numpy as np
import manifold3d as mf

from params import *  # noqa: F401,F403
from geom import (S_DIR, N_DIR, unit, m_box, m_face_box, m_cyl, m_tube, m_hull, union, _m4)
from printed import KEY_PLANE, pilot_positions, sock_to_key, groove_lines


def _k(u, v, w):
    """Key frame (Δs, Δn, w = 85.2 − x) to unit."""
    return unit(P4_X[1] - w, KEY_S + u, KEY_N + v)


def m_key_box(u0, u1, v0, v1, w0, w1):
    c = mf.Manifold.cube([u1 - u0, v1 - v0, w1 - w0]).translate([u0, v0, w0])
    R = np.column_stack([S_DIR, N_DIR, [-1, 0, 0]])
    return c.transform(_m4(R, unit(P4_X[1], KEY_S, KEY_N)))


def m_key_cyl(u, v, w0, w1, d, seg=24):
    return m_cyl(_k(u, v, w0), _k(u, v, w1), d, seg)


def m_key_prism(poly_uv, w0, w1):
    cs = mf.CrossSection([np.asarray(poly_uv, float)], mf.FillRule.EvenOdd)
    m = mf.Manifold.extrude(cs, w1 - w0).translate([0, 0, w0])
    R = np.column_stack([S_DIR, N_DIR, [-1, 0, 0]])
    return m.transform(_m4(R, unit(P4_X[1], KEY_S, KEY_N)))


def ribbon(path_sn, x0, x1, t):
    """FPC ribbon along a polyline in (s, n), x0..x1 wide (per point), t thick."""
    pts = np.asarray([p[:2] for p in path_sn], float)
    hulls = []
    for i in range(len(pts) - 1):
        a, b = pts[i], pts[i + 1]
        d = (b - a) / np.linalg.norm(b - a)
        nrm = np.array([-d[1], d[0]]) * t / 2
        corners = []
        for p, (xa, xb) in ((a, path_sn[i][2]), (b, path_sn[i + 1][2])):
            for q in (p + nrm, p - nrm):
                corners += [unit(xa, *q), unit(xb, *q)]
        hulls.append(m_hull(corners))
    return union(hulls)


def header_pin_xy(k):
    """Pi header pin k (1–40) in the unit frame, §3.4."""
    col = (k - 1) // 2
    return HEADER_PIN1[0] - HEADER_PITCH * col, HEADER_PIN1[1] + (HEADER_PITCH if k % 2 == 0 else 0.0)


def build_proxies():
    P = {}
    # ---------------------------------------------------------------- panel, §3.1
    P["panel_face"] = m_face_box(-PANEL_X, PANEL_X, *PANEL_S, PANEL_N[0], PANEL_N[0] + PANEL_FACE_T)
    P["panel_glass"] = m_face_box(-PANEL_X, PANEL_X, *PANEL_S, PANEL_N[0] + PANEL_FACE_T, PANEL_N[1])
    hw0, hw = TAIL_W_GLASS / 2, TAIL_W / 2
    cs, cn = TAIL_FOLD_C
    path = [(PANEL_S[0], cn - TAIL_FOLD_R, (TAIL_X - hw0, TAIL_X + hw0))]
    for k, a in enumerate(np.linspace(-90, -270, 25)):
        w = hw0 + (hw - hw0) * min(1.0, k / 6)
        path.append((cs + TAIL_FOLD_R * math.cos(math.radians(a)), cn + TAIL_FOLD_R * math.sin(math.radians(a)),
                     (TAIL_X - w, TAIL_X + w)))
    path.append((TAIL_END_S, TAIL_RUN_N, (TAIL_X - hw, TAIL_X + hw)))
    P["panel_tail"] = ribbon(path, None, None, TAIL_T)

    # ---------------------------------------------------------------- foam, §3.1 and S5
    foam = [m_face_box(x - FOAM_W / 2, x + FOAM_W / 2, *FOAM_BOTTOM_S, *FOAM_N) for x in FOAM_BOTTOM_X]   # item 8
    foam += [m_face_box(x - 5, x + 5, *FOAM_TOP_S, *FOAM_N) for x in FOAM_TOP_X]
    P["foam"] = union(foam)

    # ---------------------------------------------------------------- driver HAT, §3.2
    P["hat_pcb"] = m_face_box(*HAT_X, *HAT_S, *HAT_N)
    P["hat_header"] = m_face_box(*HAT_HEADER_X, *HAT_HEADER_S, HAT_N[1], HAT_HEADER_N)
    parts = [m_face_box(*FPC_SOCKET[0], *FPC_SOCKET[1], *FPC_SOCKET[2]),
             m_face_box(*GH_SOCKET[0], *GH_SOCKET[1], *GH_SOCKET[2])]
    parts += [m_face_box(*xr, *sr, HAT_N[0] - SWITCH_H, HAT_N[0]) for xr, sr in HAT_SWITCHES]
    parts += [m_face_box(-12.0, -5.0, 30.0, 37.0, HAT_N[1], HAT_N[1] + 1.2),       # ALW TSSOP
              m_face_box(4.0, 8.5, 32.0, 36.5, HAT_N[1], HAT_N[1] + 2.5)]          # ALW inductor
    P["hat_parts"] = union(parts)

    # ---------------------------------------------------------------- Pi 5, §3.3
    pcb = m_box(*PI_X, *PI_Y, *PI_Z)
    for x, y in STANDOFF_XY:
        pcb = pcb - m_cyl((x, y, PI_Z[0] - 1), (x, y, PI_Z[1] + 1), PI_HOLE_D)
    P["pi_pcb"] = pcb
    z0 = PORT_BLOCK_Z0
    metal = [m_box(-19.0, -1.5, 42.5, 55.7, z0, PI_Z[0]),          # USB 3.0 stack, Pi Y 29.1
             m_box(-19.0, -1.5, 60.4, 73.6, z0, PI_Z[0]),          # USB 2.0 stack, Pi Y 47
             m_box(-19.0, 2.0, 22.2, 38.2, z0 + 2.0, PI_Z[0]),     # RJ45, Pi Y 10.2
             m_box(53.35, 62.25, 19.8, 27.3, 18.3, PI_Z[0]),       # USB-C, Pi X 11.2
             m_box(39.95, 46.45, 19.8, 27.3, 18.5, PI_Z[0]),       # micro-HDMI 0
             m_box(26.55, 33.05, 19.8, 27.3, 18.5, PI_Z[0])]       # micro-HDMI 1
    P["pi_metal"] = union(metal)
    pin_xy = [header_pin_xy(k) for k in range(1, 41)]
    xs = [p[0] for p in pin_xy]
    black = [m_box(27.0, 44.0, 34.0, 51.0, 20.3, PI_Z[0]),          # SoC, §3.3
             m_box(10.0, 24.0, 33.0, 48.0, 20.5, PI_Z[0]),          # ALW RAM
             m_box(0.0, 7.0, 40.0, 47.0, 20.6, PI_Z[0]),            # ALW RP1
             m_box(min(xs) - 1.27, max(xs) + 1.27, HEADER_PIN1[1] - 1.27, HEADER_PIN1[1] + HEADER_PITCH + 1.27,
                   HEADER_BASE_Z, PI_Z[0])]                         # header base
    P["pi_black"] = union(black)
    P["pi_pins"] = union([m_box(x - 0.32, x + 0.32, y - 0.32, y + 0.32, HEADER_PIN_Z0, HEADER_BASE_Z) for x, y in pin_xy])
    # heatsink: fins vertical, tips at z 9.0
    hs = [m_box(14.0, 56.0, 28.0, 64.0, 18.8, 20.3)]
    hs += [m_box(x, x + 1.0, 28.0, 64.0, HEATSINK_Z0, 18.81) for x in np.arange(14.5, 55.0, 3.0)]
    P["heatsink"] = union(hs)
    # Dupont housings on the nine GH lead pins, §3.4
    gh_xy = [header_pin_xy(k) for k in GH_PINS]
    P["dupont"] = union([m_box(x - 1.27, x + 1.27, y - 1.27, y + 1.27, *DUPONT_Z) for x, y in gh_xy])
    # GH lead: plug at the HAT, nine wires over the backer, through the roof notch, down the plate recess
    plug = m_face_box(*GH_PLUG[0], *GH_PLUG[1], *GH_PLUG[2])
    order = sorted(range(9), key=lambda i: -gh_xy[i][0])
    wires = []
    for j, i in enumerate(order):
        xp, yp = gh_xy[i]
        xg = -2.5 + (j - 4) * 1.1
        xb = 50.5 + j * 1.0
        y_run = 80.5
        n_b = 6.9                               # on the backer's rear face (n 6.48)
        s_b = (y_run - TOE_Y + SIN * n_b) / COS
        on_backer = unit(xb, s_b, n_b)
        pts = [unit(xg, GH_PLUG[1][1], n_b), unit(xg, 64.0, n_b), unit(xb, s_b - 6.0, n_b), on_backer,
               (xb, y_run, 26.0), (xb, y_run, 3.0), (xb, 79.6, 1.5), (xp, 78.0, 1.5), (xp, yp, 1.5),
               (xp, yp, DUPONT_Z[0])]
        wires.append(m_tube(pts, 0.8, 8))
    P["gh_lead"] = union([plug] + wires)

    # ---------------------------------------------------------------- J2 press-fit pins, housing and leads, §3.7
    xa, xb2 = J2_X
    base = m_box(xa - 1.27, xb2 + 1.27, J2_Y - 1.27, J2_Y + 1.27, HEADER_BASE_Z, PI_Z[0])
    pins = [m_box(x - 0.32, x + 0.32, J2_Y - 0.32, J2_Y + 0.32, HEADER_PIN_Z0, PI_Z[1] + 1.0) for x in J2_X]
    P["j2_pins"] = union([base] + pins)
    P["j2_housing"] = m_box(xa - 1.27, xb2 + 1.27, J2_Y - 1.27, J2_Y + 1.27, *DUPONT_Z)
    joint_x = [74.73, 77.27]
    joint = m_box(73.46, 78.54, 28.73, 31.27, 14.0, 39.0)        # ALW: male in female, near (76, 30, 25)
    leads = []
    for x, xj, yr, (dn, sp, (ts0, ts1)) in ((xa, joint_x[0], 29.6, groove_lines()[0]),
                                            (xb2, joint_x[1], 31.2, groove_lines()[1])):
        leads.append(m_tube([(x, J2_Y, DUPONT_Z[0]), (x, J2_Y, 1.65), (x, 25.0, 1.65), (x, 27.5, 2.7), (x, yr, 2.7),
                             (xj, yr, 2.7), (xj, 30.0, 10.0), (xj, 30.0, 14.0)], 1.3, 8))
        # item 6: the lead lies in the ramped groove along the tab's centreline; its stripped end
        # (WIRE_D) lies on the tab, under the shoe's nose, and ends on the tab
        T = P4_X[1] - P4_X[0]
        s_edge = P4_S[0] - KEY_S
        w_edge = T - GROOVE_D + LEAD_D / 2 + 0.02          # on the groove floor
        w_pocket = T - P4_POCKET_DEPTH + LEAD_D / 2 + 0.02
        w_tab = T - P4_POCKET_DEPTH + SOCKET_TAB_T + WIRE_D / 2 + 0.01   # on the tab
        leads.append(m_tube([(xj, 30.0, 39.0), (xj, 30.0, 41.0), _k(s_edge - 4.6, dn, w_edge - 1.0),
                             _k(s_edge - 0.6, dn, w_edge), _k(s_edge, dn, w_edge), _k(sp, dn, w_pocket)], LEAD_D, 8))
        leads.append(m_tube([_k(sp, dn, w_tab), _k(ts1 - 0.3, dn, w_tab)], WIRE_D, 8))
    P["j2_leads"] = union([joint] + leads)

    # ---------------------------------------------------------------- USB-C L-adapter (ALW), §3.5 and S3
    a = ADP
    P["usbc_adapter"] = union([m_box(a["x"] - a["w"] / 2, a["x"] + a["w"] / 2, *a["rec_y"], *a["rec_z"]),
                               m_box(a["x"] - a["w"] / 2, a["x"] + a["w"] / 2, *a["neck_y"], *a["neck_z"])])

    # ---------------------------------------------------------------- USB-A panel socket and lead, §3.6
    cx, cy = USBA_CUT[0], USBA_CUT[1]
    flange = m_box(cx - 19.0, cx + 19.0, cy - 6.0, cy + 6.0, P2_T, P2_T + 2.0)
    for x, y in USBA_EARS:
        flange = flange - m_cyl((x, y, 0), (x, y, 5), P2_SCREW_D)
    P["usba_socket"] = union([flange, m_box(cx - 7.25, cx + 7.25, cy - 3.75, cy + 3.75, P2_T + 2.0, 17.0)])
    px, py, pz = USBA_PORT
    plug = m_box(px - 16.0, px, py - 8.0, py + 8.0, pz - 4.0, pz + 4.0)
    cable = m_tube([(px - 8.0, py, pz + 4.0), (px - 8.0, py, 16.0), (cx + 13.0, cy + 10.0, 19.5),
                    (cx, cy, 19.5), (cx, cy, 17.0)], 4.5, 12)
    P["usba_lead"] = union([plug, cable])
    scr = []
    for x, y in USBA_EARS:
        scr += [m_cyl((x, y, -M3_HEAD_H), (x, y, 0), M3_HEAD_D, 24), m_cyl((x, y, 0), (x, y, P2_T + 2.0 + 2.4), 3.0, 16),
                m_cyl((x, y, P2_T + 2.0), (x, y, P2_T + 2.0 + 2.4), 6.35, 6) - m_cyl((x, y, 0), (x, y, 9), 3.0, 16)]
    P["screws_usba"] = union(scr)

    # ---------------------------------------------------------------- key: switch, stem, cap, socket, screws
    # housing below the flange 2.2 (x 85.2–87.4), flange 0.8, housing above 2.0 (CHK §5)
    sw = [m_key_box(-6.9, 6.9, -6.9, 6.9, -2.2, 0.0), m_key_box(-7.5, 7.5, -7.5, 7.5, -3.0, -2.2),
          m_key_box(-6.9, 6.9, -6.9, 6.9, -5.0, -3.0)]
    sw += [m_key_cyl(0, 0, 0.0, 2.65, 3.2), m_key_cyl(0, -P4_LOC_DN, 0.0, 2.65, 1.8), m_key_cyl(0, P4_LOC_DN, 0.0, 2.65, 1.8)]
    sw += [m_key_cyl(*SLEEVE_A, 0.0, 3.0, 1.0, 12), m_key_cyl(*SLEEVE_B, 0.0, 3.0, 1.0, 12)]
    P["key_switch"] = union(sw)
    cap_w0 = -(HALF_W + KEY_PROUD - P4_X[1])
    P["key_stem"] = union([m_key_box(-1.5, 1.5, -3.45, -2.25, cap_w0 + 2.0, -5.0),
                           m_key_box(-1.5, 1.5, 2.25, 3.45, cap_w0 + 2.0, -5.0)])
    P["keycap"] = m_key_box(-8.25, 8.25, -8.75, 8.75, cap_w0, cap_w0 + 2.0)
    floor_w = P4_X[1] - P4_X[0] - P4_POCKET_DEPTH
    body = m_key_prism([sock_to_key(u, v) for u, v in SOCKET_BODY][::-1], floor_w, floor_w + SOCKET_BODY_H)
    tabs = []
    for (u0, u1), (v0, v1) in SOCKET_TABS:
        (s0, n0), (s1, n1) = sock_to_key(u0, v0), sock_to_key(u1, v1)
        tabs.append(m_key_box(min(s0, s1), max(s0, s1), min(n0, n1), max(n0, n1), floor_w, floor_w + SOCKET_TAB_T))
    sleeves = [m_key_cyl(*SLEEVE_A, floor_w, floor_w + SOCKET_SLEEVE_H, SOCKET_SLEEVE_D),
               m_key_cyl(*SLEEVE_B, floor_w, floor_w + SOCKET_SLEEVE_H, SOCKET_SLEEVE_D)]
    P["key_socket"] = union([body] + tabs + sleeves)
    scr = []
    for ps, pn in pilot_positions():
        w_back = P4_X[1] - P4_X[0]
        w_head = w_back + SHOE_T + WASHER_T
        scr += [m_key_cyl(ps, pn, w_back + SHOE_T, w_head, WASHER_OD) - m_key_cyl(ps, pn, w_back, w_head + 1, WASHER_ID),
                m_key_cyl(ps, pn, w_head, w_head + M2_HEAD_H, M2_HEAD_D),
                m_key_cyl(ps, pn, w_head - M2_L, w_head, M2_D, 16)]
    P["screws_key"] = union(scr)

    # ---------------------------------------------------------------- ballast, feet, inserts, screws
    P["bars"] = union([m_box(x0, x1, *BAR_Y, *BAR_Z) for x0, x1 in BAR_X])
    P["feet"] = union([m_cyl((x, 0, z), (x, FOOT_H, z), FOOT_D, 48) for x, z in FOOT_XZ])
    # item 5: inserts from the boss face at z 3.5; M3 × 6 button heads seated in the Ø6.0 × 1.8 counterbores
    P["inserts"] = union([m_cyl((x, y, BOSS_Z0), (x, y, BOSS_Z0 + INSERT_L), INSERT_HOLE_D, 32) -
                          m_cyl((x, y, 0), (x, y, 12), INSERT_ID, 32) for x, y in BOSS_XY])
    P["screws_rear"] = union([m_cyl((x, y, P2_CBORE_DEPTH - M3_HEAD_H), (x, y, P2_CBORE_DEPTH), M3_HEAD_D, 32)
                              for x, y in BOSS_XY] +
                             [m_cyl((x, y, P2_CBORE_DEPTH), (x, y, P2_CBORE_DEPTH + M3_L), 3.0, 32) for x, y in BOSS_XY])
    P["screws_pi"] = union([m_cyl((x, y, PI_Z[1]), (x, y, PI_Z[1] + M25_HEAD_H), M25_HEAD_D, 24) for x, y in STANDOFF_XY] +
                           [m_cyl((x, y, PI_Z[1] - M25_L), (x, y, PI_Z[1]), 2.5, 24) for x, y in STANDOFF_XY])
    for k, m in P.items():
        assert not m.is_empty() and m.status() == mf.Error.NoError, k
    return P


def psu_plug_envelope():
    """Item 7: the PSU plug's envelope through the USB-C window (the window inset by 0.5), for the
    interference check only (not drawn)."""
    e = PSU_ENV
    cs = mf.CrossSection.square((e["w"] - 2 * e["r"], e["h"] - 2 * e["r"])).translate(
        (-(e["w"] - 2 * e["r"]) / 2, -(e["h"] - 2 * e["r"]) / 2)).offset(e["r"], mf.JoinType.Round, 2.0, 48)
    return mf.Manifold.extrude(cs, e["z"][1] - e["z"][0]).translate([e["x"], e["y"], e["z"][0]])
