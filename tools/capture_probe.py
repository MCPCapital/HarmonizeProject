#!/usr/bin/env python3
"""Measure capture-device behavior without saving video frames."""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from typing import Iterable

import cv2
import numpy as np


BACKENDS = {
    "any": cv2.CAP_ANY,
    "gstreamer": cv2.CAP_GSTREAMER,
    "v4l2": cv2.CAP_V4L2,
}


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = round((len(ordered) - 1) * fraction)
    return ordered[index]


def milliseconds_summary(values: list[float]) -> dict[str, float] | None:
    if not values:
        return None
    return {
        "min": round(min(values) * 1000, 3),
        "median": round(statistics.median(values) * 1000, 3),
        "p95": round(percentile(values, 0.95) * 1000, 3),
        "max": round(max(values) * 1000, 3),
    }


def numeric_summary(values: list[float]) -> dict[str, float] | None:
    if not values:
        return None
    return {
        "min": round(min(values), 3),
        "median": round(statistics.median(values), 3),
        "p95": round(percentile(values, 0.95), 3),
        "max": round(max(values), 3),
    }


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Probe frame delivery and timing without storing frames. "
            "Pixel-derived statistics are disabled unless --content-metrics is used."
        )
    )
    parser.add_argument("--label", required=True, help="Physical test condition")
    parser.add_argument("--duration", type=float, default=15.0, help="Probe duration in seconds")
    parser.add_argument("--device-index", type=int, default=0, help="OpenCV video device index")
    parser.add_argument(
        "--backend",
        choices=sorted(BACKENDS),
        default="gstreamer",
        help="OpenCV capture backend",
    )
    parser.add_argument(
        "--content-metrics",
        action="store_true",
        help="Calculate aggregate luma and frame-change metrics; no frames are saved",
    )
    args = parser.parse_args(argv)
    if args.duration <= 0:
        parser.error("--duration must be greater than zero")
    return args


def probe(args: argparse.Namespace) -> tuple[dict[str, object], int]:
    started_at = datetime.now(timezone.utc).isoformat()
    capture = cv2.VideoCapture(args.device_index, BACKENDS[args.backend])

    result: dict[str, object] = {
        "schema_version": 1,
        "label": args.label,
        "started_at": started_at,
        "device_index": args.device_index,
        "backend_requested": args.backend,
        "content_metrics_enabled": args.content_metrics,
        "opened": capture.isOpened(),
    }

    if not capture.isOpened():
        capture.release()
        return result, 2

    result["backend_actual"] = capture.getBackendName()
    result["reported"] = {
        "width": int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)),
        "height": int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT)),
        "fps": round(capture.get(cv2.CAP_PROP_FPS), 3),
        "fourcc": int(capture.get(cv2.CAP_PROP_FOURCC)),
    }

    successes = 0
    failures = 0
    read_times: list[float] = []
    arrivals: list[float] = []
    shape_counts: Counter[str] = Counter()
    luma_means: list[float] = []
    frame_differences: list[float] = []
    near_identical = 0
    previous_sample: np.ndarray | None = None
    first_frame_at: float | None = None

    started = time.monotonic()
    deadline = started + args.duration

    try:
        while time.monotonic() < deadline:
            read_started = time.monotonic()
            ok, frame = capture.read()
            read_finished = time.monotonic()

            if not ok:
                failures += 1
                time.sleep(0.01)
                continue

            successes += 1
            if first_frame_at is None:
                first_frame_at = read_finished
            read_times.append(read_finished - read_started)
            arrivals.append(read_finished)
            shape_counts["x".join(str(value) for value in frame.shape)] += 1

            if args.content_metrics:
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                sample = gray[::8, ::8].astype(np.float32)
                luma_means.append(float(sample.mean()))
                if previous_sample is not None and previous_sample.shape == sample.shape:
                    difference = float(np.mean(np.abs(sample - previous_sample)))
                    frame_differences.append(difference)
                    if difference < 0.5:
                        near_identical += 1
                previous_sample = sample
    finally:
        capture.release()

    elapsed = time.monotonic() - started
    intervals = [later - earlier for earlier, later in zip(arrivals, arrivals[1:])]

    result.update(
        {
            "target_duration_seconds": args.duration,
            "elapsed_seconds": round(elapsed, 3),
            "successful_frames": successes,
            "failed_reads": failures,
            "effective_fps": round(successes / elapsed, 3) if elapsed else 0.0,
            "first_frame_ms": (
                round((first_frame_at - started) * 1000, 3)
                if first_frame_at is not None
                else None
            ),
            "shape_counts": dict(sorted(shape_counts.items())),
            "resolution_or_format_changes": max(0, len(shape_counts) - 1),
            "read_time_ms": milliseconds_summary(read_times),
            "interarrival_ms": milliseconds_summary(intervals),
        }
    )

    if args.content_metrics:
        comparison_count = len(frame_differences)
        result["content"] = {
            "luma_mean": numeric_summary(luma_means),
            "temporal_mean_absolute_difference": numeric_summary(frame_differences),
            "near_identical_comparisons": near_identical,
            "comparison_count": comparison_count,
            "near_identical_fraction": (
                round(near_identical / comparison_count, 6)
                if comparison_count
                else None
            ),
        }

    return result, 0 if successes else 3


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    result, return_code = probe(args)
    json.dump(result, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
