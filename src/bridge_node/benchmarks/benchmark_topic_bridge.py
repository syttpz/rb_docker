#!/usr/bin/env python3
"""Observe a ROS2 topic for a fixed window and report bandwidth/rate/latency/jitter.

Meant to be run standalone (not part of the bridge_node build) on *both*
ends of a corelink_bridge_node hop at once: once against the source topic
(e.g. on the robot, before the bridge) and once against the republished
topic (e.g. on the receiving machine, after the bridge). Comparing the two
JSON outputs -- message counts, byte totals, latency -- gives bandwidth,
delivered rate, and loss for that hop. This script only observes one side;
it does not do the comparison itself.

Latency is (arrival wall-clock time) - (message header.stamp), so it is
only meaningful for messages with a std_msgs/Header and only as accurate
as NTP sync between the two machines being compared.

Usage:
    ros2 run --prefix 'python3' ... # not a ROS2 package entry point, just:
    python3 benchmark_topic_bridge.py --topic /camera/camera/color/image_raw/compressed \
        --type sensor_msgs/msg/CompressedImage --duration 20 --qos best_effort \
        --out results/compressed_source.json
"""
import argparse
import importlib
import json
import time

import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy


def resolve_msg_type(type_str: str):
    pkg, _, msg_name = type_str.split("/")
    module = importlib.import_module(f"{pkg}.msg")
    return getattr(module, msg_name)


class TopicObserver(Node):
    def __init__(self, topic: str, msg_type, qos: QoSProfile):
        super().__init__("benchmark_topic_observer")
        self.arrival_times = []
        self.sizes = []
        self.latencies_ms = []
        self.create_subscription(msg_type, topic, self._on_message, qos)

    def _on_message(self, msg):
        now = time.time()
        self.arrival_times.append(now)

        size = len(msg.data) if hasattr(msg, "data") else None
        self.sizes.append(size if size is not None else 0)

        if hasattr(msg, "header"):
            stamp = msg.header.stamp.sec + msg.header.stamp.nanosec * 1e-9
            if stamp > 0:  # unset stamps are all-zero, not a real capture time
                self.latencies_ms.append((now - stamp) * 1000.0)


def summarize(count_measured, duration_s, sizes, arrival_times, latencies_ms):
    total_bytes = sum(sizes)
    inter_arrival_ms = [
        (arrival_times[i] - arrival_times[i - 1]) * 1000.0
        for i in range(1, len(arrival_times))
    ]

    def stats(values, unit_label):
        if not values:
            return None
        arr = np.array(values)
        return {
            "mean": float(arr.mean()),
            "median": float(np.median(arr)),
            "p95": float(np.percentile(arr, 95)),
            "min": float(arr.min()),
            "max": float(arr.max()),
            "stddev": float(arr.std()),
            "samples": len(values),
            "unit": unit_label,
        }

    return {
        "count": count_measured,
        "duration_s": duration_s,
        "rate_hz": count_measured / duration_s if duration_s > 0 else 0.0,
        "bytes_total": total_bytes,
        "bandwidth_Bps": total_bytes / duration_s if duration_s > 0 else 0.0,
        "message_size_bytes": stats(sizes, "bytes"),
        "latency_ms": stats(latencies_ms, "ms"),
        "inter_arrival_jitter_ms": stats(inter_arrival_ms, "ms"),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--topic", required=True)
    parser.add_argument("--type", required=True, help="e.g. sensor_msgs/msg/CompressedImage")
    parser.add_argument("--duration", type=float, default=20.0, help="seconds to observe")
    parser.add_argument("--qos", choices=["best_effort", "reliable"], default="best_effort")
    parser.add_argument("--out", required=True, help="path to write JSON summary")
    parser.add_argument("--label", default="", help="free-text note stored in the output")
    args = parser.parse_args()

    msg_type = resolve_msg_type(args.type)
    qos = QoSProfile(depth=10, history=HistoryPolicy.KEEP_LAST)
    qos.reliability = (
        ReliabilityPolicy.BEST_EFFORT if args.qos == "best_effort" else ReliabilityPolicy.RELIABLE
    )

    rclpy.init()
    node = TopicObserver(args.topic, msg_type, qos)

    print(f"Observing '{args.topic}' ({args.type}, {args.qos}) for {args.duration}s...")
    start = time.time()
    while time.time() - start < args.duration:
        rclpy.spin_once(node, timeout_sec=0.1)
    actual_duration = time.time() - start

    result = summarize(
        len(node.arrival_times), actual_duration, node.sizes, node.arrival_times, node.latencies_ms
    )
    result["topic"] = args.topic
    result["type"] = args.type
    result["qos"] = args.qos
    result["label"] = args.label
    result["observed_at_unix"] = start

    with open(args.out, "w") as f:
        json.dump(result, f, indent=2)

    print(json.dumps(result, indent=2))
    node.destroy_node()
    rclpy.shutdown()


if __name__ == "__main__":
    main()
