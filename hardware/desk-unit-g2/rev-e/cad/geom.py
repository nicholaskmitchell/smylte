"""Frames and small solid helpers shared by the printed parts (build123d) and the proxies (manifold3d)."""
import math
import numpy as np
from build123d import (Plane, Location, Pos, Box, Cylinder, Polygon, SlotOverall, RectangleRounded,
                       extrude, Compound)
import manifold3d as mf

from params import SIN, COS, TOE_Y, TOE_Z

# ------------------------------------------------------------------ frames
S_DIR = np.array([0.0, COS, -SIN])      # up the face
N_DIR = np.array([0.0, -SIN, -COS])     # inward normal
N_OUT = -N_DIR


def unit(x, s, n):
    """Face frame (x, s, n) to unit frame (x, y, z), §1.1."""
    return np.array([x, TOE_Y + COS * s - SIN * n, TOE_Z - SIN * s - COS * n])


def face_sn(y, z):
    """Unit (y, z) to face (s, n), §1.1."""
    return SIN * (TOE_Z - z) + COS * (y - TOE_Y), COS * (TOE_Z - z) - SIN * (y - TOE_Y)


# build123d plane whose local (X, Y, Z) is (x, s, −n)
FACE = Plane(origin=(0, TOE_Y, TOE_Z), x_dir=(1, 0, 0), z_dir=tuple(N_OUT))
# local (X, Y) = (s, −n), extrusion along +x
SN_PLANE = Plane(origin=(0, TOE_Y, TOE_Z), x_dir=tuple(S_DIR), z_dir=(1, 0, 0))


def face_box(x0, x1, s0, s1, n0, n1):
    return FACE.location * Pos((x0 + x1) / 2, (s0 + s1) / 2, -(n0 + n1) / 2) * Box(x1 - x0, s1 - s0, n1 - n0)


def box(x0, x1, y0, y1, z0, z1):
    return Pos((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2) * Box(x1 - x0, y1 - y0, z1 - z0)


def prism_x(pts_zy, x0, x1):
    """Polygon in the side profile (z, y), extruded across x0..x1."""
    f = Plane.YZ.offset(x0) * Polygon(*[(y, z) for z, y in pts_zy], align=None)
    return extrude(f, amount=x1 - x0, dir=(1, 0, 0))


def prism_sn(pts_sn, x0, x1):
    """Polygon in the face profile (s, n), extruded across x0..x1."""
    f = SN_PLANE.offset(x0) * Polygon(*[(s, -n) for s, n in pts_sn], align=None)
    return extrude(f, amount=x1 - x0, dir=(1, 0, 0))


def zcyl(x, y, z0, z1, d):
    return Pos(x, y, (z0 + z1) / 2) * Cylinder(d / 2, z1 - z0)


def slot(center, axis, depth_dir, length, width, d0, d1):
    """Full-round slot, long axis `axis`, cut along depth_dir from d0 to d1 (offsets from center)."""
    c = np.asarray(center, float) + np.asarray(depth_dir, float) * d0
    pl = Plane(origin=tuple(c), x_dir=tuple(axis), z_dir=tuple(depth_dir))
    return extrude(pl * SlotOverall(length, width), amount=d1 - d0)


def rrect_prism(plane, cx, cy, w, h, r, amount):
    return extrude(plane * Pos(cx, cy) * RectangleRounded(w, h, r), amount=amount)


def cut_all(body, tools):
    """Cut a list of tools: fuse them first (OCC's multi-tool cut misbehaves where tools overlap)."""
    tools = list(tools)
    tool = tools[0].fuse(*tools[1:]) if len(tools) > 1 else tools[0]
    return body.cut(tool)


def compound(shapes):
    return Compound(children=list(shapes))


# ------------------------------------------------------------------ manifold helpers
def _m4(R, t):
    return np.hstack([np.asarray(R, float), np.asarray(t, float).reshape(3, 1)])


FACE_R = np.column_stack([[1, 0, 0], S_DIR, -N_DIR])   # local (x, s, −n) → unit
FACE_T = np.array([0, TOE_Y, TOE_Z])


def m_box(x0, x1, y0, y1, z0, z1):
    return mf.Manifold.cube([x1 - x0, y1 - y0, z1 - z0]).translate([x0, y0, z0])


def m_face_box(x0, x1, s0, s1, n0, n1):
    c = mf.Manifold.cube([x1 - x0, s1 - s0, n1 - n0]).translate([x0, s0, -n1])
    return c.transform(_m4(FACE_R, FACE_T))


def m_face(m):
    """Place a manifold built in face-local (x, s, −n) coordinates."""
    return m.transform(_m4(FACE_R, FACE_T))


def m_cyl(p0, p1, d, seg=32, d1=None):
    p0, p1 = np.asarray(p0, float), np.asarray(p1, float)
    v = p1 - p0
    L = float(np.linalg.norm(v))
    c = mf.Manifold.cylinder(L, d / 2, (d if d1 is None else d1) / 2, seg)
    z = v / L
    a = np.array([1.0, 0, 0]) if abs(z[0]) < 0.9 else np.array([0, 1.0, 0])
    x = np.cross(a, z)
    x /= np.linalg.norm(x)
    y = np.cross(z, x)
    return c.transform(_m4(np.column_stack([x, y, z]), p0))


def m_tube(points, d, seg=12):
    pts = [np.asarray(p, float) for p in points]
    parts = [m_cyl(a, b, d, seg) for a, b in zip(pts[:-1], pts[1:]) if np.linalg.norm(b - a) > 1e-6]
    parts += [mf.Manifold.sphere(d / 2, seg).translate(list(p)) for p in pts[1:-1]]
    return union(parts)


def m_hull(points):
    return mf.Manifold.hull_points(np.asarray(points, float))


def union(ms):
    ms = [m for m in ms if m is not None and not m.is_empty()]
    if not ms:
        return mf.Manifold()
    return mf.Manifold.batch_boolean(ms, mf.OpType.Add)


def m_from_mesh(v, f):
    mesh = mf.Mesh(vert_properties=np.asarray(v, np.float32), tri_verts=np.asarray(f, np.uint32))
    return mf.Manifold(mesh)


def m_arrays(m):
    mesh = m.to_mesh()
    return np.asarray(mesh.vert_properties)[:, :3].astype(float), np.asarray(mesh.tri_verts).astype(np.int64)


def rot_x(deg):
    a = math.radians(deg)
    return np.array([[1, 0, 0], [0, math.cos(a), -math.sin(a)], [0, math.sin(a), math.cos(a)]])
