"""Smylte desk unit G2 · Rev E · the short wedge.

Run from hardware/desk-unit-g2/rev-e with the CAD environment:
    python cad/wedge.py            # everything: STLs, viewer/parts.json, report.json, sections, preview PNGs
    python cad/wedge.py --no-shots # skip the Playwright screenshots

Every number is in cad/params.py, named and tagged with its spec section (wedge-spec.md, with the
lead's fixes in wedge-fixes.md applied). This file only builds, places, checks and writes.
"""
import sys
sys.dont_write_bytecode = True
import json
import os
import time
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from params import *  # noqa: E402,F401,F403
import geom  # noqa: E402
from geom import S_DIR, N_DIR, N_OUT, unit, m_from_mesh, m_arrays  # noqa: E402
import printed  # noqa: E402
import proxies  # noqa: E402
import checks  # noqa: E402
import outputs  # noqa: E402
from meshing import tessellate, from_arrays  # noqa: E402
from build123d import extrude  # noqa: E402

REV_E = os.path.dirname(HERE)
OUT = {k: os.path.join(REV_E, k) for k in ("stl", "viewer", "preview")}

# print orientation (rows map the unit frame to bed axes), §2
FACE_DOWN = np.array([[1, 0, 0], -S_DIR, N_DIR])          # P1, P3: face (n = 0) on the bed, +n up
FRONT_DOWN_P4 = np.array([S_DIR, N_DIR, [-1, 0, 0]])     # P4: front face x 85.2 on the bed
IDENT = np.eye(3)

PRINTED_PARTS = [
    # key, STL name, builder, rotation to the bed (None = already in bed coordinates)
    ("shell", "p1-shell", printed.build_shell, FACE_DOWN),
    ("rear_plate", "p2-rear-plate", printed.build_rear_plate, IDENT),
    ("backer", "p3-backer", printed.build_backer, FACE_DOWN),
    ("key_carrier", "p4-key-carrier", printed.build_key_carrier, FRONT_DOWN_P4),
    ("fit_gauge", "p5-fit-gauge", printed.build_gauge, None),
    ("fit_gauge_choc", "p5b-choc-coupon", printed.build_choc_coupon, None),
    ("fit_gauge_usbc", "p5c-usbc-coupon", printed.build_usbc_coupon, None),
    ("fit_gauge_vent", "p5d-vent-coupon", printed.build_vent_coupon, None),
    ("key_shoe", "p6-key-shoe", printed.build_shoe, None),
]
GAUGE_GROUP = ("fit_gauge", "fit_gauge_choc", "fit_gauge_usbc", "fit_gauge_vent")   # one bed frame, centred on the frame


def thin_features(P):
    """the wordmark's 0.4-deep relief and the boss cone tips (points, not walls)"""
    s, n = geom.face_sn(P[:, 1], P[:, 2])
    mark = ((P[:, 0] > MARK_BOX_X[0] - 2) & (P[:, 0] < MARK_BOX_X[1] + 2) & (s > MARK_BOX_S[0] - 2) &
            (s < MARK_BOX_S[1] + 2) & (n < MARK_DEPTH + 0.05))
    tips = np.zeros(len(P), bool)
    for x, y in BOSS_XY:
        half = BOSS_CONE_HALF_UPPER if y > 60 else BOSS_CONE_HALF_LOWER
        apex = BOSS_Z1 + BOSS_D / 2 / np.tan(np.radians(half))
        tips |= np.linalg.norm(P - np.array([x, y, apex]), axis=1) < 2.5
    return mark | tips


def M4(R, t=(0, 0, 0)):
    M = np.eye(4)
    M[:3, :3] = R
    M[:3, 3] = t
    return M


def log(*a):
    print(*a, flush=True)


def main(shots=True):
    t0 = time.time()
    for d in OUT.values():
        os.makedirs(d, exist_ok=True)
    report = {"rev": "E", "form": "short wedge (form A) with both grafts",
              "sources": ["wedge-spec.md", "wedge-fixes.md (overrides)", "wedge-spec-check.md"], "parts": {}}

    # ------------------------------------------------------------ build and tessellate the printed parts
    shapes, fine, coarse, bedM = {}, {}, {}, {}
    for key, stl, build, R in PRINTED_PARTS:
        s = build()
        assert s.is_valid and len(s.solids()) == 1, key
        shapes[key] = s
        fine[key] = tessellate(s, 0.02, 0.15)
        coarse[key] = tessellate(s, 0.06, 0.35)
        log(f"built {key:16s} {s.volume / 1000:7.2f} cm³  ({time.time() - t0:5.1f} s)")
    # bed placement: rotate, then centre in X and Y with the lowest point on the bed
    gauge_shift = None
    for key, stl, build, R in PRINTED_PARTS:
        Rm = IDENT if R is None else R
        V = fine[key].V @ Rm.T
        if key in GAUGE_GROUP:
            if gauge_shift is None:
                lo, hi = V.min(0), V.max(0)
                gauge_shift = np.array([-(lo[0] + hi[0]) / 2, -(lo[1] + hi[1]) / 2, -lo[2]])
            sh = gauge_shift.copy()
            sh[2] = -V[:, 2].min()
        else:
            lo, hi = V.min(0), V.max(0)
            sh = np.array([-(lo[0] + hi[0]) / 2, -(lo[1] + hi[1]) / 2, -lo[2]])
        bedM[key] = M4(Rm, sh)

    # ------------------------------------------------------------ STLs and per-part checks
    failures = []
    for key, stl, build, R in PRINTED_PARTS:
        tm = fine[key].transformed(bedM[key]).merged()
        outputs.write_stl(tm, os.path.join(OUT["stl"], stl + ".stl"))
        ext = tm.bounds[1] - tm.bounds[0]
        wt = checks.watertight(tm)
        vol = tm.volume / 1000
        entry = {"stl": f"stl/{stl}.stl", "bed_mm": [round(float(e), 2) for e in ext],
                 "fits_175": bool(np.all(ext <= BED_MAX + 1e-6)), "volume_cm3": round(vol, 2),
                 "petg_g": round(vol * PETG, 1), "watertight": wt}
        if not entry["fits_175"]:
            failures.append(f"{stl}: bed {ext.round(2).tolist()} exceeds {BED_MAX}")
        if not wt["ok"]:
            failures.append(f"{stl}: not a single watertight manifold solid {wt}")
        entry["min_wall"] = checks.min_wall(coarse[key], exclude=thin_features if key == "shell" else None)
        if entry["min_wall"]:
            entry["min_wall"]["frame"] = "bed" if R is None else "unit (assembly position)"
        entry["overhangs"] = checks.overhangs(coarse[key].transformed(bedM[key]))
        report["parts"][key] = entry
        oh = [o for o in entry["overhangs"] if not o["bridge"]]
        log(f"checked {stl:18s} bed {entry['bed_mm']}  {vol:6.2f} cm³ {entry['petg_g']:6.1f} g  "
            f"watertight={wt['ok']}  min wall {entry['min_wall']['mm'] if entry['min_wall'] else '-'}  "
            f"overhangs {len(oh)} ({sum(o['area_mm2'] for o in oh):.1f} mm²), bridges {len(entry['overhangs']) - len(oh)}")
    if failures:
        for f in failures:
            log("FAIL:", f)
        raise SystemExit("printed-part check failed: " + "; ".join(failures))

    # ------------------------------------------------------------ assembly: printed parts, mark, proxies
    asm_mesh = {}       # viewer meshes (per face)
    asm_solid = {}      # manifolds for interference
    asm_tm = {}         # welded trimesh for measuring and sections
    for key in ("shell", "rear_plate", "backer", "key_carrier"):
        asm_mesh[key] = coarse[key]
        tmw = fine[key].merged()
        asm_tm[key] = tmw
        asm_solid[key] = m_from_mesh(tmw.vertices, tmw.faces)
    shoe_fine, shoe_coarse = fine["key_shoe"], coarse["key_shoe"]
    cv, cf = [], []
    coff = 0
    shoe_tms = []
    for i in (0, 1):
        M = printed.shoe_to_unit(i)
        a = shoe_fine.transformed(M).merged()
        shoe_tms.append(a)
        b = shoe_coarse.transformed(M)
        cv.append(b.V)
        cf.append(b.F + coff)
        coff += len(b.V)
    import trimesh
    shoes_tm = trimesh.util.concatenate(shoe_tms)
    asm_tm["key_shoes"] = shoes_tm
    asm_solid["key_shoes"] = geom.union([m_from_mesh(t.vertices, t.faces) for t in shoe_tms])
    from meshing import Mesh
    asm_mesh["key_shoes"] = Mesh(np.vstack(cv), np.vstack(cf), np.zeros(sum(len(f) for f in cf), int))
    # wordmark: letters as a thin floor in the recess, the period filled with enamel
    letters, period = printed.mark_faces(MARK_DEPTH)
    from build123d import Compound
    mark = Compound(children=[extrude(f, amount=0.05, dir=tuple(N_OUT)) for f in letters])
    mark_p = Compound(children=[extrude(f, amount=MARK_PERIOD_FILL, dir=tuple(N_OUT)) for f in period])
    for key, s in (("mark", mark), ("mark_period", mark_p)):
        m = tessellate(s, 0.01, 0.2)
        asm_mesh[key] = m
        tmw = m.merged()
        asm_tm[key] = tmw
        asm_solid[key] = m_from_mesh(tmw.vertices, tmw.faces)
    P = proxies.build_proxies()
    for key, m in P.items():
        V, F = m_arrays(m)
        asm_solid[key] = m
        asm_tm[key] = trimesh.Trimesh(V, F, process=False)
        asm_mesh[key] = from_arrays(V, F)
    log(f"assembly: {len(asm_solid)} parts ({time.time() - t0:5.1f} s)")

    # ------------------------------------------------------------ meta for the viewer
    def quad(x, s0, s1, n):
        return [unit(-x, s0, n).round(4).tolist(), unit(x, s0, n).round(4).tolist(),
                unit(x, s1, n).round(4).tolist(), unit(-x, s1, n).round(4).tolist()]
    sh_lo, sh_hi = asm_tm["shell"].bounds
    meta = {
        "rev": "E", "form": "short wedge",
        "W": round(float(sh_hi[0] - sh_lo[0]), 2), "D": round(float(sh_hi[2] - sh_lo[2]), 2),
        "H": round(float(sh_hi[1] - asm_tm["feet"].bounds[0][1]), 2),
        "depth_real": round(float(sh_hi[2] - sh_lo[2]), 2),
        "tilt": 90 - LEAN, "lean": LEAN, "n_out": [0, round(SIN, 6), round(COS, 6)],
        "screen": quad(ACTIVE_X, ACTIVE_S[0], ACTIVE_S[1], PANEL_N[0] - 0.02),
        "panel_front": quad(PANEL_X, PANEL_S[0], PANEL_S[1], PANEL_N[0] - 0.01),
        "key": {"pos": unit(HALF_W, KEY_S, KEY_N).round(2).tolist(), "y": round(float(unit(0, KEY_S, KEY_N)[1]), 2),
                "z": round(float(unit(0, KEY_S, KEY_N)[2]), 2), "from_rear": round(float(unit(0, KEY_S, KEY_N)[2]), 2),
                "proud": KEY_PROUD, "cut": KEY_CUT, "plate": KEY_PLATE},
        "bezel": {"side": round(HALF_W - WIN_OUT_X[1], 2), "top": round(FACE_L - WIN_OUT_S[1], 2), "chin": WIN_OUT_S[0]},
        "bbox": {"min": [round(float(v), 2) for v in np.min([t.bounds[0] for t in asm_tm.values()], 0)],
                 "max": [round(float(v), 2) for v in np.max([t.bounds[1] for t in asm_tm.values()], 0)]},
        "frame": "mm; +y up (0 at the desk); +z toward the viewer (0 at the rear outer face); +x right seen from the front",
        "info": {k: {"bed": report["parts"][k]["bed_mm"], "cm3": report["parts"][k]["volume_cm3"]} for k in report["parts"]},
        "printed": ["shell", "rear_plate", "backer", "key_carrier", "key_shoes"],
    }
    order = ["shell", "mark", "mark_period", "rear_plate", "backer", "key_carrier", "key_shoes"] + list(P)
    size = outputs.write_parts_json({k: asm_mesh[k] for k in order}, meta, os.path.join(OUT["viewer"], "parts.json"))
    log(f"viewer/parts.json {size / 1e6:.2f} MB, {len(order)} parts")

    # ------------------------------------------------------------ interference matrix (with the PSU plug envelope, item 7)
    env = proxies.psu_plug_envelope()
    solids = {k: asm_solid[k] for k in order} | {"psu_plug_envelope": env}
    rows = checks.interference(solids)
    report["interference"] = {"threshold_mm3": INTERFERENCE_MIN, "pairs_checked": len(solids) * (len(solids) - 1) // 2,
                              "listed": rows,
                              "note": "psu_plug_envelope is a check-only solid (item 7), not drawn in the viewer"}
    # ------------------------------------------------------------ key numbers
    report["key_numbers"] = checks.measure(asm_tm, meta)
    # ------------------------------------------------------------ design checks (review items 1, 2, 5, 7, 8)
    walls = checks.web_walls(asm_solid["shell"], asm_solid["rear_plate"])
    dc = {
        "webs_between_through_openings": {"limit_mm": WEB_MIN, "walls": checks.web_check(walls),
                                          "note": "through-openings only (option A): slots, windows, holes, the USB-A "
                                                  "cutout and its ears. The face (window) and the right flank (key "
                                                  "cutout) carry one opening each. Recesses are under skins."},
        "skins_under_recesses": {"limit_mm": SKIN_MIN, "recesses": checks.skin_check(asm_tm)},
        "wordmark_layer1": checks.mark_layer1(asm_solid["shell"]),
        "rear_closure_pads": checks.pad_check(asm_solid["rear_plate"], asm_solid["shell"],
                                              next(w[2] for w in walls if w[0] == "rear_plate")),
        "rear_screws": checks.screw_check(P["screws_rear"], asm_tm["shell"]),
        "psu_plug_envelope": checks.envelope_check(env, asm_solid["rear_plate"]),
        "foam_pads": checks.foam_check(P["foam"]),
    }
    dc["webs_between_through_openings"]["ok"] = all(w["ok"] for w in dc["webs_between_through_openings"]["walls"])
    dc["skins_under_recesses"]["ok"] = all(r["ok"] for r in dc["skins_under_recesses"]["recesses"])
    report["design_checks"] = dc
    report["vent_areas_mm2"] = checks.vent_areas(walls)
    report["fasteners"] = fasteners()
    skins = [r for r in dc["skins_under_recesses"]["recesses"] if r["part"] == "rear_plate" and "skin_min_mm" in r]
    worst = min(skins, key=lambda r: r["skin_min_mm"])
    report["parts"]["rear_plate"]["min_wall_reported"] = {
        "mm": min(worst["skin_min_mm"], report["parts"]["rear_plate"]["min_wall"]["mm"]), "at": worst["at"],
        "where": "the skin where band A's 0.4 outer recesses overlap the 1.0 header recess (y 80-84)",
        "accepted": "by the lead: three layers, not load-bearing; exempt from the web check"}
    report["meta"] = {k: meta[k] for k in ("W", "D", "H", "key", "bezel")}
    # ------------------------------------------------------------ sections
    secs = [(("x", 0.0), "section-x0"), (("x", -40.0), "section-x-40"), (("x", 60.0), "section-x60-pi"),
            (("x", 84.0), "section-x84-key"), (("y", 36.0), "section-y36")]
    report["sections"] = {}
    for pl, name in secs:
        title = (f"Section x = {pl[1]:g} (z to the right, front on the right; y up)" if pl[0] == "x"
                 else f"Section y = {pl[1]:g} (plan: x to the right, front at the bottom)")
        cut = checks.section_svg(asm_tm, outputs.COLOURS | {"mark": "#000", "key_shoes": "#3a3d40"}, pl, "Rev E short wedge. " + title,
                                 os.path.join(OUT["preview"], name + ".svg"))
        report["sections"][name] = cut
    design_failures = [k for k, v in dc.items() if not v["ok"]]
    report["notes"] = [
        "Overhang locations are in bed coordinates (print orientation); min-wall locations are in the unit frame "
        "for P1–P4 and in bed coordinates for P5, P5b, P5c and P6.",
        "P5 is delivered as four STLs that share one bed frame (frame, Choc coupon, USB-C coupon, top-land vent "
        "coupon), so each STL is a single solid; load them together to print the spec's one plate, or print P5b or "
        "P5d on its own.",
        "PROVISIONAL, set from the parts you buy: the USB-C saddle and adapter allowance (S3), the USB-A cutout and "
        "ear holes, the heatsink, the HAT parts and header position, the Pi port blocks.",
    ]
    with open(os.path.join(REV_E, "report.json"), "w") as f:
        json.dump(report, f, indent=1)
    summary(report)
    if design_failures:
        raise SystemExit("design check failed: " + ", ".join(design_failures))
    # ------------------------------------------------------------ preview
    outputs.write_preview()
    if shots:
        outputs.shoot()
    log(f"done in {time.time() - t0:.0f} s")


def fasteners():
    """§7.2 with review item 5 (M3 × 6 in counterbores). Lengths in mm."""
    return [
        {"qty": 4, "part": f"M3 × {M3_L:g} button head (ISO 7380)", "where": "P2 to P1",
         "note": f"heads in Ø{P2_CBORE_D:g} × {P2_CBORE_DEPTH:g} counterbores from outside, "
                 f"{P2_T + P2_PAD_T - P2_CBORE_DEPTH:.1f} of P2 under the head (plate and Ø{P2_PAD_D:g} pad)"},
        {"qty": 4, "part": f"M3 heat-set insert, for a Ø{INSERT_HOLE_D:g} hole, {INSERT_L:g} long", "where": "P1 bosses",
         "note": f"hole Ø{INSERT_HOLE_D:g} × {INSERT_HOLE_DEPTH:g} from the boss face at z {BOSS_Z0:g}"},
        {"qty": 4, "part": f"M2.5 × {M25_L:g} pan head, thread-forming for plastics", "where": "Pi to standoffs",
         "note": f"Ø{PILOT_D:g} pilots"},
        {"qty": 2, "part": f"M2 × {M2_L:g} pan head, thread-forming, plus 2 M2 washers (DIN 125, OD {WASHER_OD:g})",
         "where": "key tab clamps (P6 shoes)", "note": f"Ø{PILOT_KEY_D:g} pilots"},
        {"qty": 2, "part": "supplied with the USB-A lead (provisional: M3 × 8 + M3 nuts)", "where": "USB-A socket",
         "note": "PROVISIONAL"},
    ]


def summary(r):
    log("\n================ Rev E short wedge: checks ================")
    log(f"{'part':18s} {'bed X × Y × Z (mm)':26s} {'cm³':>7s} {'PETG g':>7s}  watertight  min wall")
    for k, p in r["parts"].items():
        b = " × ".join(f"{v:.1f}" for v in p["bed_mm"])
        mw = p["min_wall"]
        log(f"{k:18s} {b:26s} {p['volume_cm3']:7.2f} {p['petg_g']:7.1f}  {str(p['watertight']['ok']):10s}  "
            f"{(str(mw['mm']) + ' at ' + str(mw['at'])) if mw else '-'}"
            + (f"; {mw['mm_excluding']} at {mw['at_excluding']} excluding {mw['excluding']}" if mw and 'mm_excluding' in mw else ""))
    tot = sum(p["petg_g"] for k, p in r["parts"].items() if k != "key_shoe") + 3 * r["parts"]["key_shoe"]["petg_g"]
    log(f"PETG total (P1–P5d, P6 × 4): {tot:.0f} g")
    log("\nOverhangs in print orientation (> 45° from vertical, not bridges under 15 mm):")
    for k, p in r["parts"].items():
        oh = [o for o in p["overhangs"] if not o["bridge"]]
        nb = len(p["overhangs"]) - len(oh)
        if not oh:
            log(f"  {k}: none ({nb} bridge regions)")
        for o in oh:
            log(f"  {k}: {o['area_mm2']:7.2f} mm² at {o['worst_from_vertical']}° near bed {o['at']} extent {o['extent']}")
    log("\nInterference over 0.05 mm³:")
    for row in r["interference"]["listed"]:
        tag = "intended: " + row["why"] if row["intended"] else "NOT INTENDED"
        log(f"  {row['a']:14s} × {row['b']:14s} {row['mm3']:9.3f} mm³  {tag}")
    log("\nKey numbers re-measured from the model:")
    for k, v in r["key_numbers"].items():
        log(f"  {k}: {json.dumps(v)}")
    log("\nDesign checks:")
    dc = r.get("design_checks", {})
    for w in dc.get("webs_between_through_openings", {}).get("walls", []):
        log(f"  web {w['part']} {w['wall']}: {w['through_openings']} openings, {w['open_area_mm2']} mm², narrowest "
            f"{w['narrowest_web']}, ok={w['ok']}")
    for s in dc.get("skins_under_recesses", {}).get("recesses", []):
        log(f"  skin {s['part']} {s['recess']}: min {s.get('skin_min_mm')} at {s.get('at')} {s.get('skins_mm')} "
            f"({s['rule']}) ok={s['ok']}")
    for k in ("wordmark_layer1", "rear_closure_pads", "rear_screws", "psu_plug_envelope", "foam_pads"):
        if k in dc:
            log(f"  {k}: {json.dumps(dc[k])}")
    log(f"\nVent areas (mm²): {json.dumps(r.get('vent_areas_mm2'))}")


if __name__ == "__main__":
    main(shots="--no-shots" not in sys.argv)
