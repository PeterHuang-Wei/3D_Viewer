import os
import pytest
from core.model import Document, STL_QUALITY, stl_triangle_count


def doc_with_cylinder():
    d = Document()
    d.add_feature("cylinder", {"r": 10, "h": 20})
    return d


def test_stl_quality_levels(tmp_path):
    d = doc_with_cylinder()
    counts = []
    for name in ("標準", "高(預設)", "超高"):
        p = str(tmp_path / f"{name[0]}.stl")
        counts.append(d.export_stl(p, *STL_QUALITY[name]))
        assert os.path.getsize(p) == 84 + 50 * counts[-1]       # 二進位格式
    assert counts[0] < counts[1] < counts[2]                     # 越精細三角形越多


def test_stl_ascii_and_empty(tmp_path):
    d = doc_with_cylinder()
    p = str(tmp_path / "a.stl")
    n = d.export_stl(p, 0.05, 0.2, ascii=True)
    assert open(p).read().startswith("solid") and stl_triangle_count(p) == n
    with pytest.raises(ValueError):
        Document().export_stl(str(tmp_path / "b.stl"))
