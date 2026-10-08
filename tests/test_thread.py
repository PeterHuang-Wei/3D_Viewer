import math
import pytest
from core import thread as T
from core import features as F


def test_spec():
    assert T.parse_spec("M10 粗牙 (P1.5)") == (10, 1.5)
    assert T.CUSTOM in T.spec_list()


def test_rod_volume():
    rod = T.make_threaded_rod(10, 1.5, 15)
    assert rod.isValid()
    r_root = 5 - 0.6134 * 1.5
    v_min = math.pi * r_root ** 2 * 15
    v_max = math.pi * 25 * 15
    assert v_min < rod.Volume() < v_max


def test_left_hand():
    assert T.make_threaded_rod(8, 1.25, 10, left_hand=True).isValid()


def test_threaded_hole():
    block = F.make_box(30, 30, 20)           # z: -10..10
    res = T.threaded_hole(block, 10, 1.5, 20, (0, 0, -10), "Z")
    assert res.isValid() and res.Volume() < block.Volume()
    side = T.threaded_hole(block, 6, 1.0, 30, (-15, 0, 0), "X")
    assert side.Volume() < block.Volume()
    with pytest.raises(ValueError):
        T.threaded_hole(block, 6, 1.0, 5, (100, 0, 0), "Z")


def test_bad_args():
    with pytest.raises(ValueError):
        T.make_threaded_rod(2, 3, 10)
