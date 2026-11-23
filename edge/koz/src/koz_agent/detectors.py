"""Person detectors: ``yolox`` (YOLOX-tiny on ONNX Runtime, CPU) and ``sim`` (the generated
scene's true boxes).

YOLOX-tiny takes 416×416: the frame is resized keeping its ratio into the top-left corner of a
canvas filled with 114, kept BGR and float32 0–255 with no mean/std (the current YOLOX
preprocessing; ``legacy_norm`` switches to the old RGB, /255, mean/std one), NCHW. The output
(1, 3549, 85) is decoded on the grids of strides 8, 16 and 32: ``xy = (xy + grid) * stride``,
``wh = exp(wh) * stride``; score = objectness × the person class (0), kept from 0.35, then NMS at
IoU 0.45 and scaled back to the frame.
"""

from __future__ import annotations

import statistics
import time
from functools import lru_cache
from pathlib import Path
from typing import Protocol

import cv2
import numpy as np

from .frames import Detection, Frame

INPUT_SIZE = (416, 416)  # (height, width)
STRIDES = (8, 16, 32)
PERSON = 0
MEAN = np.array([0.485, 0.456, 0.406], np.float32)
STD = np.array([0.229, 0.224, 0.225], np.float32)


class Detector(Protocol):
    name: str

    def detect(self, frame: Frame) -> list[Detection]: ...


class SimDetector:
    """Returns the scene's exact boxes; for frames from anything else, nothing."""

    name = "sim"
    last_ms = 0.0

    def detect(self, frame: Frame) -> list[Detection]:
        return list(frame.truth or [])


def preprocess(
    image: np.ndarray, size: tuple[int, int] = INPUT_SIZE, *, legacy_norm: bool = False
) -> tuple[np.ndarray, float]:
    """BGR frame → (1, 3, H, W) float32 tensor and the resize ratio."""
    h, w = image.shape[:2]
    ratio = min(size[0] / h, size[1] / w)
    nh, nw = int(h * ratio), int(w * ratio)
    canvas = np.full((size[0], size[1], 3), 114, np.uint8)
    resized = cv2.resize(image, (nw, nh), interpolation=cv2.INTER_LINEAR)
    canvas[:nh, :nw] = resized
    tensor = canvas.astype(np.float32)
    if legacy_norm:
        tensor = (tensor[:, :, ::-1] / 255.0 - MEAN) / STD
    tensor = np.ascontiguousarray(tensor.transpose(2, 0, 1)[None], dtype=np.float32)
    return tensor, ratio


@lru_cache(maxsize=4)
def grids(size: tuple[int, int] = INPUT_SIZE, strides: tuple[int, ...] = STRIDES):
    """The (N, 2) grid offsets and (N, 1) strides of every output row, in output order."""
    all_grids, all_strides = [], []
    for stride in strides:
        hs, ws = size[0] // stride, size[1] // stride
        xv, yv = np.meshgrid(np.arange(ws), np.arange(hs))
        all_grids.append(np.stack((xv, yv), 2).reshape(-1, 2))
        all_strides.append(np.full((hs * ws, 1), stride))
    return (
        np.concatenate(all_grids).astype(np.float32),
        np.concatenate(all_strides).astype(np.float32),
    )


def decode(raw: np.ndarray, size: tuple[int, int] = INPUT_SIZE) -> np.ndarray:
    """Raw output (1, N, 85) or (N, 85) → boxes as centre/size in input pixels (a copy)."""
    out = np.array(raw, dtype=np.float32, copy=True).reshape(-1, raw.shape[-1])
    grid, stride = grids(size)
    if out.shape[0] != grid.shape[0]:
        raise ValueError(f"expected {grid.shape[0]} rows for {size}, got {out.shape[0]}")
    out[:, :2] = (out[:, :2] + grid) * stride
    out[:, 2:4] = np.exp(out[:, 2:4]) * stride
    return out


def nms(boxes: np.ndarray, scores: np.ndarray, iou_threshold: float) -> list[int]:
    """Greedy non-maximum suppression on (N, 4) x1 y1 x2 y2 boxes; indices kept, best first."""
    x1, y1, x2, y2 = boxes[:, 0], boxes[:, 1], boxes[:, 2], boxes[:, 3]
    areas = np.maximum(0, x2 - x1) * np.maximum(0, y2 - y1)
    order = scores.argsort()[::-1]
    keep: list[int] = []
    while order.size:
        i = int(order[0])
        keep.append(i)
        rest = order[1:]
        xx1 = np.maximum(x1[i], x1[rest])
        yy1 = np.maximum(y1[i], y1[rest])
        xx2 = np.minimum(x2[i], x2[rest])
        yy2 = np.minimum(y2[i], y2[rest])
        inter = np.maximum(0, xx2 - xx1) * np.maximum(0, yy2 - yy1)
        iou = inter / np.maximum(areas[i] + areas[rest] - inter, 1e-9)
        order = rest[iou <= iou_threshold]
    return keep


def postprocess(
    raw: np.ndarray,
    ratio: float,
    frame_w: int,
    frame_h: int,
    *,
    size: tuple[int, int] = INPUT_SIZE,
    score_threshold: float = 0.35,
    nms_threshold: float = 0.45,
) -> list[Detection]:
    pred = decode(raw, size)
    scores = pred[:, 4] * pred[:, 5 + PERSON]
    keep = scores >= score_threshold
    if not keep.any():
        return []
    pred, scores = pred[keep], scores[keep]
    boxes = np.empty((pred.shape[0], 4), np.float32)
    boxes[:, 0] = pred[:, 0] - pred[:, 2] / 2
    boxes[:, 1] = pred[:, 1] - pred[:, 3] / 2
    boxes[:, 2] = pred[:, 0] + pred[:, 2] / 2
    boxes[:, 3] = pred[:, 1] + pred[:, 3] / 2
    boxes /= ratio
    boxes[:, [0, 2]] = boxes[:, [0, 2]].clip(0, frame_w)
    boxes[:, [1, 3]] = boxes[:, [1, 3]].clip(0, frame_h)
    result = []
    for i in nms(boxes, scores, nms_threshold):
        x1, y1, x2, y2 = (float(v) for v in boxes[i])
        if x2 - x1 >= 2 and y2 - y1 >= 2:
            result.append(Detection((x1, y1, x2, y2), float(scores[i])))
    return result


class YoloxDetector:
    name = "yolox"

    def __init__(
        self,
        model_path: Path | str,
        *,
        intra_threads: int = 2,
        inter_threads: int = 1,
        score_threshold: float = 0.35,
        nms_threshold: float = 0.45,
        legacy_norm: bool = False,
    ) -> None:
        import onnxruntime as ort

        options = ort.SessionOptions()
        options.intra_op_num_threads = intra_threads
        options.inter_op_num_threads = inter_threads
        options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        self.session = ort.InferenceSession(
            str(model_path), options, providers=["CPUExecutionProvider"]
        )
        model_input = self.session.get_inputs()[0]
        self.input_name = model_input.name
        shape = model_input.shape
        h = shape[2] if isinstance(shape[2], int) else INPUT_SIZE[0]
        w = shape[3] if isinstance(shape[3], int) else INPUT_SIZE[1]
        self.size = (int(h), int(w))
        self.score_threshold = score_threshold
        self.nms_threshold = nms_threshold
        self.legacy_norm = legacy_norm
        self.last_ms = 0.0

    def detect(self, frame: Frame) -> list[Detection]:
        return self.detect_image(frame.image)

    def detect_image(self, image: np.ndarray) -> list[Detection]:
        started = time.perf_counter()
        tensor, ratio = preprocess(image, self.size, legacy_norm=self.legacy_norm)
        raw = self.session.run(None, {self.input_name: tensor})[0]
        h, w = image.shape[:2]
        result = postprocess(
            raw, ratio, w, h, size=self.size, score_threshold=self.score_threshold,
            nms_threshold=self.nms_threshold,
        )
        self.last_ms = (time.perf_counter() - started) * 1000.0
        return result

    def benchmark(self, image: np.ndarray, runs: int = 10, warmup: int = 2) -> float:
        """Median milliseconds per frame (preprocess + inference + decode)."""
        for _ in range(warmup):
            self.detect_image(image)
        times = []
        for _ in range(runs):
            self.detect_image(image)
            times.append(self.last_ms)
        return statistics.median(times)
