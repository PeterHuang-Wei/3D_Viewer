import cadquery as cq
from viewer.mesh import shape_to_mesh, shape_to_edges
from viewer.quality import QUALITY


def test_finer_quality_gives_smoother_circles():
    cyl = cq.Workplane().circle(10).extrude(5).val()
    cells, edge_pts = [], []
    for name in ("低", "標準", "高", "超高"):
        q = QUALITY[name]
        cells.append(shape_to_mesh(cyl, q["tol"], q["ang"]).n_cells)
        edge_pts.append(shape_to_edges(cyl, q["edge_pts"]).n_points)
    assert cells == sorted(cells) and len(set(cells)) == 4
    assert edge_pts == sorted(edge_pts) and len(set(edge_pts)) == 4


def test_straight_edges_use_two_points():
    box = cq.Workplane().box(1, 1, 1).val()
    assert shape_to_edges(box, 256).n_points == 12 * 2


def test_sketch_circle_segments():
    from core import sketch2d as S
    from core import features as F
    c = S.circle((0, 0), 5)
    wp = F.WORLD_PLANES["XY"]
    assert len(S.polylines_global([c], wp, 64)[0]) < len(S.polylines_global([c], wp, 512)[0])
