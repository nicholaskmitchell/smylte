"""Tessellation of build123d shapes with CAD-face ids, and the merged watertight meshes."""
import numpy as np
import trimesh
from OCP.BRep import BRep_Tool
from OCP.TopLoc import TopLoc_Location
from OCP.TopAbs import TopAbs_Orientation

TOL, ANG = 0.02, 0.15


class Mesh:
    """Unmerged (per CAD face) triangles: V (n,3), F (m,3), fid (m,)."""

    def __init__(self, V, F, fid):
        self.V, self.F, self.fid = np.asarray(V, float), np.asarray(F, np.int64), np.asarray(fid, np.int64)

    def transformed(self, M):
        V = self.V @ M[:3, :3].T + M[:3, 3]
        F = self.F if np.linalg.det(M[:3, :3]) > 0 else self.F[:, ::-1]
        return Mesh(V, F, self.fid)

    def merged(self):
        """Watertight trimesh: coincident vertices welded."""
        key = np.round(self.V, 5)
        uniq, inv = np.unique(key, axis=0, return_inverse=True)
        F = inv.reshape(-1)[self.F]
        keep = (F[:, 0] != F[:, 1]) & (F[:, 1] != F[:, 2]) & (F[:, 0] != F[:, 2])
        m = trimesh.Trimesh(uniq, F[keep], process=False)
        m.metadata["fid"] = self.fid[keep]
        return m


def tessellate(shape, tol=TOL, ang=ANG):
    shape.mesh(tol, ang)
    Vs, Fs, ids, off = [], [], [], 0
    for k, face in enumerate(shape.faces()):
        loc = TopLoc_Location()
        poly = BRep_Tool.Triangulation_s(face.wrapped, loc)
        if poly is None:
            continue
        trsf = loc.Transformation()
        rev = face.wrapped.Orientation() == TopAbs_Orientation.TopAbs_REVERSED
        nodes = [poly.Node(i).Transformed(trsf) for i in range(1, poly.NbNodes() + 1)]
        V = np.array([(p.X(), p.Y(), p.Z()) for p in nodes])
        T = np.array([(t.Value(1), t.Value(2), t.Value(3)) for t in poly.Triangles()], np.int64) - 1
        if rev:
            T = T[:, [0, 2, 1]]
        Vs.append(V)
        Fs.append(T + off)
        ids.append(np.full(len(T), k))
        off += len(V)
    return Mesh(np.vstack(Vs), np.vstack(Fs), np.concatenate(ids))


def from_arrays(V, F):
    """Mesh from a welded (manifold) mesh: split along sharp edges so the viewer shades it flat
    where it should be flat."""
    tm = trimesh.Trimesh(V, F, process=False)
    try:
        sm = tm.smooth_shaded
        return Mesh(sm.vertices, sm.faces, np.zeros(len(sm.faces), np.int64))
    except Exception:
        V2 = V[F].reshape(-1, 3)
        return Mesh(V2, np.arange(len(V2)).reshape(-1, 3), np.zeros(len(F), np.int64))
