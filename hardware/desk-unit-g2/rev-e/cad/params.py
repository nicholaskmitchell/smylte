"""Every number of the Rev E short wedge, named, with its source.

Sources:
  "§n"  = wedge-spec.md, section n.
  "Fn"  = wedge-fixes.md, must-fix item n;  "Sn" = should-fix item n;  "FG" = its fit-gauge note.
  "CHK" = wedge-spec-check.md, where the fixes say to use the check's corrected number.
  "ALW" = an allowance chosen for a proxy or a provisional part, not a spec number.
All lengths are millimetres, angles degrees.

Frames (§1.1): unit frame x right (seen from the front), y up (0 at the desk), z toward the viewer
(0 at the rear outer face). Face frame: s up the face from the toe edge, n inward normal.
"""
import math

# ---------------------------------------------------------------- §1 frames and envelope
LEAN = 20.0                     # §1.2 lean from vertical
SIN, COS = math.sin(math.radians(LEAN)), math.cos(math.radians(LEAN))
TOE_Z, TOE_Y = 66.0, 3.5        # §1.1 toe edge (z, y); also the depth and the foot height
DEPTH = 66.0                    # §1.2
FOOT_H = 3.5                    # §1.2 feet Ø12.7 × 3.5
HALF_W = 87.4                   # §1.2 width x ±87.4
FACE_L = 124.22                 # §1.2 face length along the slope
TOP_Y = TOE_Y + FACE_L * COS    # §1.2 height 120.23
TOP_LAND_Z = TOE_Z - FACE_L * SIN   # §1.2 front-top edge z 23.51

# ---------------------------------------------------------------- §2.1 P1 shell
WALL = 2.0                      # §2.1 face plate, flanks, floor, top land
FLANK_IN = HALF_W - WALL        # 85.40
FLOOR_TOP = TOE_Y + WALL        # 5.50
LAND_UNDER = TOP_Y - WALL       # 118.23
FACE_CHAMFER = 0.4              # §2.1 face perimeter 0.4 × 45°
TOP_EDGE_R = 1.0                # §2.1 face to top-land edge
REAR_EDGE_R = 0.5               # §2.1 rear edges

# window, §2.1
WIN_IN_X, WIN_IN_S = (-82.10, 82.10), (19.70, 118.62)    # panel side, n 1.2–2.0, R 0.5
WIN_IN_R = 0.5
WIN_OUT_X, WIN_OUT_S = (-83.30, 83.30), (18.50, 119.82)  # front, n 0, R 1.7
WIN_OUT_R = 1.7
WIN_BEVEL_N = 1.2               # 45° bevel n 0–1.2, then a 0.8 land

# panel pocket and ledge rib, §2.1
POCKET_S = (10.42, 122.22)
RIB_S = (8.82, 10.42)
RIB_N = (2.0, 6.48)
NOTCH_X = (-14.07, 11.97)       # tail notch, no rib

# toe blocks and lips, §2.1
TOE_BLOCK_X = (66.0, FLANK_IN)  # |x|
TOE_BLOCK_N = 8.08
LIP_X = (68.0, 80.0)            # |x|
LIP_N = (6.58, 8.08)
LIP_S = (10.42, 12.42)
LIP_CHAMFER = 1.0

# top corner block, §2.1
CORNER_S0 = 122.22
CORNER_N = (2.0, 7.0)

# rear rebates for P2, §2.1 with F1 (rebate z 0–2.0); item 5 moves the boss faces and inserts to z 3.5
REBATE_Z = 2.0                  # F1
REBATE_X = 86.40
REBATE_Y = (4.50, 119.23)

# rear-plate screw bosses, §2.1 with F2; review item 5 moves the faces to z 3.5 (P2's pads fill z 2.0–3.5)
BOSS_XY = [(-80.9, 10.5), (80.9, 10.5), (-80.9, 113.5), (80.9, 113.5)]
BOSS_D = 8.0
BOSS_Z0, BOSS_Z1 = 3.5, 10.2    # cylinder; boss face at z 3.5 (item 5), still to z 10.2
BOSS_CONE_HALF_UPPER = 30.0     # F2: 30° half-angle, apex about z 17.1, filled to the top land
BOSS_CONE_HALF_LOWER = 25.0     # CHK §9 "≤ 25° gives a 45° worst case": the lower pair's worst side faces
                                # away from the floor fill, so 30° would overhang 50° (see report)
BOSS_WEB_T = 2.0                # §2.1 webs to the flank
INSERT_HOLE_D, INSERT_HOLE_DEPTH = 4.0, 6.5   # §2.1; item 5: from the boss face at z 3.5, ending at z 10.0

# floor slots, §2.1, S1, S8
SLOT_W = 2.4
H_SLOTS_X = [round(-70.4 + 4.4 * i, 3) for i in range(33)]
H_SLOTS_SKIP = [52.8, 57.2, 61.6, 66.0]     # USB-C adapter
H_SLOTS_Z = (4.0, 20.0)
C1_X, C1_Z = [-10.5, -6.0, -1.5, 3.0, 7.5], (28.0, 52.0)
C2_X = [-79.2, -74.8]
C3_X = [70.4, 74.8, 79.2]
C23_Z = (28.0, 51.0)            # S8: C2/C3 end at z 51.0 to clear the foot rings
C4_X = [round(-67.6 + 4.4 * i, 3) for i in range(12)] + [round(14.4 + 4.4 * i, 3) for i in range(12)]
C4_Z = (25.5, 30.5)
# top-land slots, review item 3: crosswise (long axis along x), three rows in z 4–16, x within ±75
TOP_SLOT_W, TOP_SLOT_L = 2.8, 10.5
TOP_SLOTS_Z = (4.0, 16.0)
TOP_SLOTS_X_SPAN = 75.0
TOP_SLOTS_PER_ROW = 12
TOP_SLOTS_ROW_Z = [round(TOP_SLOTS_Z[0] + TOP_SLOT_W / 2 + k * (TOP_SLOTS_Z[1] - TOP_SLOTS_Z[0] - TOP_SLOT_W) / 2, 3)
                   for k in range(3)]                      # z 5.4, 10.0, 14.6
TOP_SLOTS_X = [round(-TOP_SLOTS_X_SPAN + TOP_SLOT_L / 2 + j * (2 * TOP_SLOTS_X_SPAN - TOP_SLOT_L) / (TOP_SLOTS_PER_ROW - 1), 3)
               for j in range(TOP_SLOTS_PER_ROW)]          # centres ±69.75, pitch 12.68

# ballast bays, §2.1 with F3, F7
BAR_L, BAR_H, BAR_T = 54.0, 10.0, 20.0      # §6 bars 20 × 10 × 54 (x 54, y 10, z 20)
BAR_X = [(-70.5, -16.5), (12.5, 66.5)]      # F7: centred in the 55.0 bays
BAR_Y = (6.5, 16.5)                         # on 1 mm tape
BAR_Z = (32.0, 52.0)
RIB_XS = [(-73.0, -71.0), (-16.0, -14.0), (10.0, 12.0), (67.0, 69.0)]   # F7: outer ribs out by 1.0
BAY_RIB_Y = (FLOOR_TOP, 11.5)
BAY_RIB_Z = (32.0, 52.0)
BAY_RIB_TAPER = 23.0            # F3: rib tops taper to the floor at z 52, ≤ 23°
STOP_XS = [(-73.0, -14.0), (10.0, 69.0)]    # across each bay, rib to rib
STOP_Z_REAR, STOP_TOP_Y, STOP_Z_TOE = 52.2, 8.5, 59.2   # §2.1 rear face z 52.2, 3.0 tall, ramp to z 59.2
DENSITY_STEEL = 7.85            # g/cm³, for the bar mass check

# foot locators, §2.1, §6
FOOT_D, FOOT_RING_D, FOOT_RING_DEPTH = 12.7, 13.5, 0.2
FOOT_XZ = [(-79.9, 7.5), (79.9, 7.5), (-79.9, 58.5), (79.9, 58.5)]

# key, §2.1, §3.7
KEY_S, KEY_N = 41.83, 19.89     # = z 33.00, y 36.00
KEY_CUT = 13.90
KEY_CUT_R = 0.3
KEY_CBORE = 16.00
KEY_CBORE_DEPTH = 0.8           # x 85.40 → 86.20, leaving a 1.20 plate
KEY_PLATE = 1.2
KEY_PROUD = 5.3                 # §3.7 cap 5.3 proud

# wordmark, §2.1; review item 2: the mark's true height is 8.8, so the box is s 5.1–13.9
MARK_BOX_X = (-81.0, -47.0)
MARK_BOX_S = (5.1, 13.9)
MARK_DEPTH = 0.4
# item 2 (reading B): grow only the outer letter loops, keep the counters, then close and open the
# recess; the period is left as it is (the enamel's well)
MARK_GROW = 0.15
MARK_CLOSE = 0.3                # +0.3 then −0.3
MARK_OPEN = 0.3                 # −0.3 then +0.3
MARK_MIN_FEATURE = 0.6          # layer-1 check: face slivers and recess features
MARK_COUNTER_MIN = 1.5          # mm², the 'e' counter
MARK_LAYER1_N = 0.1             # middle of the first 0.2 layer (P1 prints face down)
MARK_PERIOD_FILL = 0.35         # ALW: enamel in the period, 0.05 below the face

# ---------------------------------------------------------------- §2.2 P2 rear plate
P2_X = 86.20
P2_Y = (4.70, 119.03)
P2_T = 2.0
P2_CORNER_R = 1.0
P2_SCREW_D = 3.4
# review item 5: a pad on the inner face at each hole, and a counterbore from outside
P2_PAD_D, P2_PAD_T = 7.5, 1.5   # z 2.0–3.5
P2_CBORE_D, P2_CBORE_DEPTH = 6.0, 1.8   # z 0–1.8, leaving 1.7 under the head
STANDOFF_XY = [(7.5, 23.5), (65.5, 23.5), (7.5, 72.5), (65.5, 72.5)]
STANDOFF_D, STANDOFF_TOP = 5.5, 21.5
STANDOFF_FILLET = 1.5
PILOT_D, PILOT_DEPTH = 2.2, 7.0
ROOF_T = 1.6
ROOF_X = (-85.0, 85.0)
ROOF_P0 = (2.00, 95.70)         # hot-side surface through (z, y)
ROOF_P1 = (23.10, 77.00)        # front edge cut by z = 23.10
ROOF_NOTCH_X = (47.0, 61.0)
ROOF_NOTCH_Y = 84.0
BAND_A_X = [round(-79.2 + 4.4 * i, 3) for i in range(37)]
BAND_A_Y, BAND_A_Y_SHORT = (80.0, 94.0), (86.0, 94.0)   # i 24–33 shortened
BAND_A_SHORT_I = range(24, 34)
OUTER_RECESS_DEPTH = 0.4        # item 4: blind recesses from the outer face
BAND_A_RECESS_Y = (80.0, 94.0)  # item 4a: slots i 24–33 read 14 long from behind (recess y 80–86)
BAND_B_RECESS_X = [4.4, 8.8]    # item 4b: the two skipped positions, so band B reads unbroken
BAND_B_X = [round(-79.2 + 4.4 * i, 3) for i in list(range(19)) + [21, 22, 23]]
BAND_B_Y = (56.0, 74.0)
LOW_SKIP = [48.4]               # item 1: dropped, its web to the USB-C window was 0.7
LOW_X = [x for x in H_SLOTS_X if x not in H_SLOTS_SKIP + LOW_SKIP]
LOW_Y = (7.0, 17.0)
USBC_WIN = (57.8, 12.0, 15.0, 11.0, 2.0)        # centre x, y, w, h, R
USBA_CUT = (-58.0, 32.0, 16.0, 9.0, 1.0)        # PROVISIONAL
USBA_EARS = [(-73.0, 32.0), (-43.0, 32.0)]
POST_XY = [(-60.0, 108.0), (60.0, 108.0)]
POST_D, POST_TIP_R = 6.0, 0.5
POST_PRELOAD = 0.1              # S6: 0.1 into the backer (spec 0.3)
RECESS_HEADER = ((26.0, 62.0), (64.0, 84.0))
RECESS_J2 = ((44.0, 57.0), (18.0, 28.0))
RECESS_DEPTH = 1.0
# S3 USB-C saddle: SET FROM THE ADAPTER YOU BUY (all ALW)
SADDLE_CHEEK_X = [(49.9, 51.5), (64.1, 65.7)]
SADDLE_GAP = 0.2                # to the adapter allowance, front and rear
SADDLE_TOP_Y = 19.5             # J2 housings start at y 20.53: 1.03 clear
SADDLE_LOW_Y = 9.0
SADDLE_ROOT_Y = 17.7            # above the USB-C window (top y 17.5)
SADDLE_WALL = 1.6
SADDLE_BAR_Y0 = 17.5            # item 7: rear bar underside flush with the window top
SADDLE_CHEEK_CHAMFER = 31.5     # item 7 (a): below y 17.5 the cheeks exist only for z ≥ 31.5 − y
# item 7: PSU plug envelope, the window inset by 0.5, checked against P2
PSU_ENV = dict(x=57.8, y=12.0, w=14.0, h=10.0, r=1.5, z=(-20.0, 14.5))

# ---------------------------------------------------------------- §2.3 P3 backer
BACKER_N = (3.98, 6.48)
BACKER_X = 85.10
BACKER_S = (10.42, 121.92)
BACKER_CORNER_R = 1.0
BACKER_TAIL_R = 1.0
PAD = 7.0
PAD_N = (6.48, 7.98)
PAD_XS = [(-31.55, 25.78), (26.45, 25.78), (-31.55, 48.78), (26.45, 48.78)]
SWITCH_POCKETS_X = [(7.9, 22.9), (-24.95, -9.95)]   # S7: 15 wide; the first stops short of the pad at x 22.95
SWITCH_POCKET_S = (22.1, 34.3)
SWITCH_POCKET_DEPTH = 1.5
GH_WIN = ((-14.5, 9.5), (45.4, 61.4), 1.5)

# ---------------------------------------------------------------- §2.4 P4 key carrier, F4, F5
P4_X = (82.0, 85.2)             # F5
P4_S = (29.83, 53.83)
P4_N = (8.89, 36.89)
P4_CENTRE_D = 3.4
P4_LOC_D = 1.9
P4_LOC_DN = 5.5
P4_POCKET_DEPTH = 1.6
P4_POCKET_GROW = 0.15
P4_SLEEVE_D = 3.0
SLEEVE_A = (-5.9, 0.0)          # (Δs, Δn) from the key centre
SLEEVE_B = (-3.8, 5.0)
PILOT_KEY_D, PILOT_KEY_DEPTH = 1.7, 3.0
PILOT_BEYOND_TAB = 1.8
GROOVE_W, GROOVE_D = 1.2, 1.0  # item 6: along each tab's centreline, 1.0 deep at the −s edge, ramped
                                # to the pocket floor (1.6) where it meets the pocket
LEAD_D, WIRE_D = 1.0, 0.6       # ALW: insulated lead and its stripped, twisted end
# Kailh CPG135001S30 outline (Adafruit 5118 spec PDF, p. 3 and 8), socket frame: u along the long
# axis, v across it, sleeve A at (0, 0), sleeve B at (5.0, 2.2). Read off the drawing, ±0.1.
SOCKET_BODY = [(-2.30, -1.90), (-1.90, -2.30), (1.65, -2.30), (2.45, -1.50), (2.45, -0.90),
               (3.25, -0.10), (7.00, -0.10), (7.30, 0.20), (7.30, 4.25), (7.00, 4.55),
               (2.95, 4.55), (2.40, 3.60), (0.90, 2.45), (-1.90, 2.45), (-2.30, 2.05)]
SOCKET_TABS = [((-4.90, -2.30), (-1.30, 1.30)), ((7.30, 9.90), (0.90, 3.50))]  # 2.6 × 2.6 pads
SOCKET_BODY_H, SOCKET_SLEEVE_H, SOCKET_SLEEVE_D = 1.80, 3.05, 2.9
SOCKET_TAB_T = 0.2              # ALW
# F4 shoe (P6): about 6 × 5 × 1.0, nose 1.0 down onto the tab
SHOE_L_OUT, SHOE_L_IN = 2.0, 4.0     # plate from the pilot: 2.0 outward, 4.0 toward the socket
SHOE_W, SHOE_T = 5.0, 1.0
SHOE_NOSE_FROM = PILOT_BEYOND_TAB - P4_POCKET_GROW + 0.2   # 0.2 clear of the pocket wall
SHOE_NOSE_W, SHOE_NOSE_H = 2.3, 1.0
SHOE_HOLE_D = 2.4
M2_HEAD_D, M2_HEAD_H, M2_L, M2_D = 3.8, 1.3, 4.0, 2.0
WASHER_OD, WASHER_ID, WASHER_T = 5.0, 2.2, 0.3

# ---------------------------------------------------------------- §8 P5 fit gauge, FG
GAUGE_S_SHIFT = 8.42
GAUGE_L = 115.8
GAUGE_BAND_T = 1.0
GAUGE_WALL_N = (1.0, 2.4)
GAUGE_WALL_T = 2.0
GAUGE_WIN_X, GAUGE_WIN_S, GAUGE_WIN_R = (-83.30, 83.30), (10.08, 111.40), 1.7
GAUGE_POCKET_X, GAUGE_POCKET_S = 85.40, (2.00, 113.80)
TAB_MINUS = ((90.0, 110.0), 85.20)
TAB_PLUS = ((6.0, 26.0), 85.60)
CHOC_COUPON = dict(L=26.0, H=26.0, T=2.0, foot_w=8.0, foot_t=1.2, cut_z=13.0)
USBC_COUPON = dict(L=30.0, W=22.0, T=2.0)
# item 3: top-land bridge proof, its own coupon P5d: a 2.0 wall leaning 20° like the top land
VENT_COUPON = dict(L=16.5, H=9.0, T=2.0, lean=LEAN, foot_w=8.0, foot_t=1.2)
COUPON_VENT_AT = (0.0, 50.0)    # ALW: bed position inside the gauge window (x, gauge s)
COUPON_CHOC_AT = (-40.0, 50.0)  # ALW: bed position inside the gauge window (x, gauge s)
COUPON_USBC_AT = (35.0, 50.0)

# ---------------------------------------------------------------- §3 electronics placement
PANEL_X = 85.10                 # 170.2 wide
PANEL_S = (10.42, 121.62)
PANEL_N = (2.00, 3.18)
PANEL_FACE_T = 0.05             # ALW, the front layer shown as its own part
ACTIVE_X = 81.6                 # 163.2
ACTIVE_S = (PANEL_S[0] + 9.78, PANEL_S[0] + 9.78 + 97.92)
TAIL_X = -1.05
TAIL_W_GLASS, TAIL_W = 22.04, 12.5
TAIL_T = 0.30
TAIL_LEAVE_N = 2.5              # CHK §4
TAIL_FOLD_C = (9.92, 4.8)       # CHK §4 fold centre (s, n), R 2.4
TAIL_FOLD_R = 2.4
TAIL_RUN_N = 7.2
TAIL_END_S = 22.18 + 3.7
FOAM_N = (BACKER_N[0] - 1.0, BACKER_N[0])     # 1.0 pads, compressed 0.8 in use (preload is intended)
FOAM_BOTTOM_X = [-77, -30, 30, 77]      # §3.1
FOAM_BOTTOM_S = (10.5, 19.5)    # item 8: 10 × 9 on the panel's chin land, short of the window (s 19.7)
FOAM_W = 10.0
FOAM_TOP_S = (118.62, 121.62)   # S5: 10 × 3 strips over the panel's land
FOAM_TOP_X = [-77, -30, 30, 77]
HAT_X = (-35.05, 29.95)         # §3.2 centre x −2.55
HAT_S = (22.18, 52.38)
HAT_N = (8.98, 10.58)
HAT_HEADER_N = 19.08
HAT_HEADER_X = (-27.95, 22.85)  # ALW 50.8 long, centred on the HAT
HAT_HEADER_S = (46.80, 51.88)   # ALW on the GH edge
FPC_SOCKET = ((-9.55, 7.45), (22.18, 26.18), (6.98, 8.98))     # ALW, centred x −1.05
HAT_SWITCHES = [((11.2, 20.4), (25.0, 31.0)), ((-21.5, -13.4), (25.0, 31.0))]  # S7 photo reading
SWITCH_H = 3.5
GH_SOCKET = ((-8.7, 3.7), (48.38, 52.38), (4.68, 8.98))        # ALW 4.3 tall
GH_PLUG = ((-8.1, 3.1), (52.38, 58.38), (4.88, 8.78))          # ALW

PI_X, PI_Y = (-16.0, 69.0), (20.0, 76.0)     # §3.3
PI_Z = (21.5, 23.1)
PI_HOLE_D = 2.7
PORT_BLOCK_Z0 = 3.5             # §1.3 USB/RJ45 allowance 18.0
HEATSINK_Z0 = 9.0               # §1.3, ≤ 12.5 total
HEADER_PIN1 = (60.63, 71.23)    # §3.4 pin 1
HEADER_PITCH = 2.54
HEADER_BASE_Z = 19.0            # 2.5 tall plastic
HEADER_PIN_Z0 = 13.0            # ALW 8.5 above the PCB
DUPONT_Z = (5.0, 19.0)          # §1.3 / CHK §3
GH_PINS = [1, 6, 11, 12, 18, 19, 22, 23, 24]
J2_X, J2_Y = (49.2, 51.7), 21.8 # §3.3 estimate
ADP = dict(x=57.8, w=12.0, rec_y=(8.75, 15.25), rec_z=(14.5, 24.5),
           neck_y=(15.25, 19.8), neck_z=(16.65, 23.15))                # ALW USB-C L-adapter body
USBA_PORT = (-19.0, 49.1, 8.0)  # ALW upper USB 3.0 port mouth (x, y, z)

# ---------------------------------------------------------------- fasteners (§7.2)
M3_HEAD_D, M3_HEAD_H, M3_L = 5.7, 1.65, 6.0   # item 5: M3 × 6 button heads (ISO 7380) in the counterbores
INSERT_L, INSERT_ID = 5.7, 3.0
M25_HEAD_D, M25_HEAD_H, M25_L = 4.5, 1.8, 6.0

# ---------------------------------------------------------------- checks
PETG = 1.27                     # g/cm³
BED_MAX = 175.0                 # every axis
OVERHANG_MAX = 45.0             # from vertical
OVERHANG_TOL = 0.5              # tessellation tolerance on the 45° limit
BRIDGE_MAX = 15.0
INTERFERENCE_MIN = 0.05         # mm³
WEB_MIN = 1.2                   # item 1: web between two through-openings in P1 or P2
SKIN_MIN = 0.6                  # item 1 (option A): material left under a recess, three layers
# vent areas (S1 formula, CHK §7): the gap under the case, and the port block that half-blocks band B
UNDER_CASE_GAP_AREA = 1517.0    # §5.2: 481.6 perimeter × 3.5, allowing for the feet
PORT_BLOCK_X = (-19.0, 2.0)     # ALW: the port block's x span (proxies), behind which band B counts half
