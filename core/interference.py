"""干涉檢查:找出實體之間互相重疊(干涉)或僅接觸的位置。"""
import cadquery as cq

from .measure import min_distance


def check(bodies, tol: float = 1e-6, include_contact: bool = True):
    """bodies: [(編號, 名稱, 形狀)]。回傳 [{"a","b","kind": "干涉"|"接觸","volume","shape","center"}]。
    先用外框快速排除;重疊體積大於 tol 視為干涉,距離為 0 但無體積視為接觸(共用面/邊)。"""
    out = []
    for i in range(len(bodies)):
        for j in range(i + 1, len(bodies)):
            (ia, na, sa), (ib, nb, sb) = bodies[i], bodies[j]
            ba, bb = sa.BoundingBox(), sb.BoundingBox()
            if (ba.xmax < bb.xmin - tol or bb.xmax < ba.xmin - tol or ba.ymax < bb.ymin - tol
                    or bb.ymax < ba.ymin - tol or ba.zmax < bb.zmin - tol or bb.zmax < ba.zmin - tol):
                continue
            try:
                common = sa.intersect(sb)
                vol = common.Volume() if common.Solids() else 0.0
            except Exception:  # noqa: BLE001
                vol, common = 0.0, None
            if vol > tol:
                out.append({"a": (ia, na), "b": (ib, nb), "kind": "干涉", "volume": vol, "shape": common,
                            "center": common.Center()})
            elif include_contact:
                try:
                    d, p, _ = min_distance(sa, sb)
                except ValueError:
                    continue
                if d <= max(tol, 1e-7):
                    out.append({"a": (ia, na), "b": (ib, nb), "kind": "接觸", "volume": 0.0, "shape": None, "center": p})
    return out
