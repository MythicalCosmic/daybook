"""The YOLOX-tiny preprocessing and decode on synthetic tensors, and the model download."""

import hashlib
import math

import httpx
import numpy as np
import pytest

from koz_agent.detectors import decode, grids, nms, postprocess, preprocess
from koz_agent.model import MODEL_SHA256, MODEL_URL, ModelError, ensure_model, model_file


def row_index(stride: int, gx: int, gy: int) -> int:
    offset = 0
    for s in (8, 16, 32):
        side = 416 // s
        if s == stride:
            return offset + gy * side + gx
        offset += side * side
    raise ValueError(stride)


def raw_output() -> np.ndarray:
    raw = np.zeros((1, 3549, 85), np.float32)
    raw[..., 4] = 0.0  # objectness 0: nothing anywhere
    return raw


def put(raw, stride, gx, gy, *, dx=0.5, dy=0.5, w=1.0, h=1.0, obj=0.9, person=0.9, other=0.0):
    i = row_index(stride, gx, gy)
    raw[0, i, :4] = (dx, dy, math.log(w), math.log(h))
    raw[0, i, 4] = obj
    raw[0, i, 5] = person
    raw[0, i, 6] = other
    return i


def test_grids_cover_strides_8_16_32_in_order():
    grid, stride = grids()
    assert grid.shape == (3549, 2) and stride.shape == (3549, 1)
    assert 52 * 52 + 26 * 26 + 13 * 13 == 3549
    assert stride[0, 0] == 8 and stride[2704, 0] == 16 and stride[-1, 0] == 32
    i = row_index(16, 3, 2)
    assert tuple(grid[i]) == (3, 2) and stride[i, 0] == 16


def test_decode_applies_grid_and_stride():
    raw = raw_output()
    i = put(raw, 16, 10, 5, dx=0.5, dy=0.25, w=2.0, h=3.0)
    out = decode(raw)
    cx, cy, w, h = out[i, :4]
    assert cx == pytest.approx((10 + 0.5) * 16)
    assert cy == pytest.approx((5 + 0.25) * 16)
    assert w == pytest.approx(2.0 * 16) and h == pytest.approx(3.0 * 16)
    j = put(raw, 32, 12, 12, dx=0.0, dy=0.0, w=4.0, h=8.0)
    out = decode(raw)
    assert tuple(out[j, :4]) == pytest.approx((384.0, 384.0, 128.0, 256.0))
    assert raw[0, i, 0] == pytest.approx(0.5)  # the input is not changed


def test_score_is_objectness_times_person_and_kept_from_035():
    raw = raw_output()
    put(raw, 8, 10, 10, obj=0.7, person=0.6)  # 0.42: kept
    put(raw, 8, 40, 40, obj=0.7, person=0.4)  # 0.28: dropped
    put(raw, 8, 25, 25, obj=0.95, person=0.1, other=0.99)  # another class: dropped
    dets = postprocess(raw, 1.0, 416, 416)
    assert len(dets) == 1 and dets[0].score == pytest.approx(0.42)


def test_nms_keeps_the_best_of_overlapping_boxes():
    boxes = np.array([[0, 0, 100, 200], [5, 5, 105, 205], [300, 0, 400, 200]], np.float32)
    scores = np.array([0.6, 0.9, 0.5], np.float32)
    assert nms(boxes, scores, 0.45) == [1, 2]
    assert nms(boxes, scores, 0.99) == [1, 0, 2]


def test_postprocess_scales_back_to_the_frame():
    raw = raw_output()
    # a person centred at (104, 104) in the 416 input, 32×96
    put(raw, 8, 12, 12, dx=1.0, dy=1.0, w=4.0, h=12.0, obj=0.9, person=0.95)
    put(raw, 8, 13, 12, dx=0.0, dy=1.0, w=4.2, h=12.0, obj=0.8, person=0.9)  # a duplicate
    ratio = min(416 / 540, 416 / 960)
    dets = postprocess(raw, ratio, 960, 540)
    assert len(dets) == 1
    x1, y1, x2, y2 = dets[0].box
    assert ((x1 + x2) / 2, (y1 + y2) / 2) == pytest.approx((104 / ratio, 104 / ratio), abs=0.01)
    assert (x2 - x1, y2 - y1) == pytest.approx((32 / ratio, 96 / ratio), abs=0.01)


def test_preprocess_letterbox_bgr_0_255():
    image = np.zeros((540, 960, 3), np.uint8)
    image[:] = (10, 20, 30)  # B, G, R
    tensor, ratio = preprocess(image)
    assert tensor.shape == (1, 3, 416, 416) and tensor.dtype == np.float32
    assert ratio == pytest.approx(416 / 960)
    rows = int(540 * ratio)
    assert tuple(tensor[0, :, 0, 0]) == (10.0, 20.0, 30.0)  # BGR kept, no scaling
    assert np.all(tensor[0, :, rows:, :] == 114.0)  # the padding below
    assert np.all(tensor[0, :, : rows - 1, :] != 114.0)


def test_legacy_norm_switch():
    image = np.zeros((416, 416, 3), np.uint8)
    image[:] = (10, 20, 30)
    tensor, _ = preprocess(image, legacy_norm=True)
    r, g, b = 30 / 255, 20 / 255, 10 / 255
    expected = ((r - 0.485) / 0.229, (g - 0.456) / 0.224, (b - 0.406) / 0.225)
    assert tuple(tensor[0, :, 5, 5]) == pytest.approx(expected, rel=1e-5)


def fake_model_server(body: bytes, counter: list):
    def handler(request: httpx.Request) -> httpx.Response:
        counter.append(str(request.url))
        assert str(request.url) == MODEL_URL
        return httpx.Response(200, content=body, headers={"content-length": str(len(body))})

    return httpx.MockTransport(handler)


def test_model_download_checks_the_pinned_sha256(tmp_path):
    calls: list = []
    with pytest.raises(ModelError, match="SHA-256"):
        ensure_model(tmp_path, transport=fake_model_server(b"not the model", calls))
    assert not model_file(tmp_path).exists() and calls == [MODEL_URL]
    body = b"a stand-in model"
    path = ensure_model(
        tmp_path,
        expected=hashlib.sha256(body).hexdigest(),
        transport=fake_model_server(body, calls),
    )
    assert path.read_bytes() == body
    # present and right: no second download
    ensure_model(
        tmp_path,
        expected=hashlib.sha256(body).hexdigest(),
        transport=fake_model_server(body, calls),
    )
    assert len(calls) == 2
    assert len(MODEL_SHA256) == 64


@pytest.mark.model
def test_the_real_model_on_a_blank_frame(monkeypatch):
    monkeypatch.delenv("KOZ_HOME", raising=False)
    path = model_file()
    if not path.exists():
        pytest.skip("the model is not downloaded (koz-agent selftest fetches it)")
    from koz_agent.detectors import YoloxDetector

    detector = YoloxDetector(ensure_model(download=False))
    assert detector.size == (416, 416)
    blank = np.zeros((540, 960, 3), np.uint8)
    assert detector.detect_image(blank) == []
    ms = detector.benchmark(blank, runs=5, warmup=1)
    print(f"YOLOX-tiny on a blank 960x540 frame: {ms:.1f} ms")
    assert ms < 2000
