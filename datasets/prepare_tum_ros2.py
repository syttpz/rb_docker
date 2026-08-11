#!/usr/bin/env python3
"""Convert a TUM RGB-D ROS 1 bag into a ROS 2 bag shaped like our RealSense stack.

The raw TUM bags are usable but not drop-in for this repo:

  * frame_ids carry a leading '/' ("/openni_rgb_optical_frame"), which tf2 in
    ROS 2 rejects outright;
  * every transform sits on /tf, including the ones that are actually static,
    so there is no /tf_static for the camera extrinsics;
  * depth is 32FC1 in metres, while the RealSense publishes 16UC1 in
    millimetres -- the compression profiling in md/thesis-research-plan.md is
    written against the 16UC1 layout;
  * topic names are the old openni ones, not /camera/camera/*.

This rewrites all of the above in a single pass and drops the ground-truth
/world -> /kinect transform into a TUM-format trajectory file next to the bag,
so ATE can be computed without digging through /tf again.

Usage:
    python3 prepare_tum_ros2.py --src ros1/rgbd_dataset_freiburg1_desk.bag \
                                --dst fr1_desk
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from rosbags.highlevel import AnyReader
from rosbags.interfaces import (
    Qos,
    QosDurability,
    QosHistory,
    QosLiveliness,
    QosReliability,
    QosTime,
)
from rosbags.rosbag2 import Writer
from rosbags.typesys import Stores, get_typestore

# /tf_static is written once at the head of the bag, so `ros2 bag play` has to
# offer it transient_local or anything that subscribes after playback starts
# (rtabmap, the bridge, rviz) never sees the camera extrinsics.
TF_STATIC_QOS = Qos(
    history=QosHistory.KEEP_LAST,
    depth=1,
    reliability=QosReliability.RELIABLE,
    durability=QosDurability.TRANSIENT_LOCAL,
    deadline=QosTime(sec=0, nsec=0),
    lifespan=QosTime(sec=0, nsec=0),
    liveliness=QosLiveliness.AUTOMATIC,
    liveliness_lease_duration=QosTime(sec=0, nsec=0),
    avoid_ros_namespace_conventions=False,
)

# TUM openni topic -> the name our bridge/rtabmap configs expect.
TOPIC_MAP = {
    '/camera/rgb/image_color': '/camera/camera/color/image_raw',
    '/camera/rgb/camera_info': '/camera/camera/color/camera_info',
    '/camera/depth/image': '/camera/camera/aligned_depth_to_color/image_raw',
    '/camera/depth/camera_info': '/camera/camera/aligned_depth_to_color/camera_info',
    '/imu': '/imu',
    '/tf': '/tf',
}

# Everything below the camera body is rigid; only world->kinect actually moves.
STATIC_EDGES = {
    ('kinect', 'openni_camera'),
    ('openni_camera', 'openni_rgb_frame'),
    ('openni_rgb_frame', 'openni_rgb_optical_frame'),
    ('openni_camera', 'openni_depth_frame'),
    ('openni_depth_frame', 'openni_depth_optical_frame'),
}

GT_EDGE = ('world', 'kinect')


def strip(frame: str) -> str:
    return frame.lstrip('/')


def rebuild_header(hdr, ts):
    """ROS 1 Header carries `seq`, ROS 2 does not -- and frame_ids need the
    leading '/' stripped before tf2 will accept them."""
    return ts.types['std_msgs/msg/Header'](
        stamp=ts.types['builtin_interfaces/msg/Time'](
            sec=hdr.stamp.sec, nanosec=hdr.stamp.nanosec),
        frame_id=strip(hdr.frame_id),
    )


def rebuild_camera_info(msg, ts):
    """ROS 1 spells the intrinsics D/K/R/P, ROS 2 spells them d/k/r/p."""
    return ts.types['sensor_msgs/msg/CameraInfo'](
        header=rebuild_header(msg.header, ts),
        height=msg.height,
        width=msg.width,
        distortion_model=msg.distortion_model,
        d=np.asarray(msg.D, dtype=np.float64),
        k=np.asarray(msg.K, dtype=np.float64),
        r=np.asarray(msg.R, dtype=np.float64),
        p=np.asarray(msg.P, dtype=np.float64),
        binning_x=msg.binning_x,
        binning_y=msg.binning_y,
        roi=ts.types['sensor_msgs/msg/RegionOfInterest'](
            x_offset=msg.roi.x_offset, y_offset=msg.roi.y_offset,
            height=msg.roi.height, width=msg.roi.width,
            do_rectify=msg.roi.do_rectify),
    )


def rebuild_imu(msg, ts):
    quat = ts.types['geometry_msgs/msg/Quaternion']
    vec3 = ts.types['geometry_msgs/msg/Vector3']
    return ts.types['sensor_msgs/msg/Imu'](
        header=rebuild_header(msg.header, ts),
        orientation=quat(x=msg.orientation.x, y=msg.orientation.y,
                         z=msg.orientation.z, w=msg.orientation.w),
        orientation_covariance=np.asarray(msg.orientation_covariance, dtype=np.float64),
        angular_velocity=vec3(x=msg.angular_velocity.x, y=msg.angular_velocity.y,
                              z=msg.angular_velocity.z),
        angular_velocity_covariance=np.asarray(msg.angular_velocity_covariance,
                                               dtype=np.float64),
        linear_acceleration=vec3(x=msg.linear_acceleration.x,
                                 y=msg.linear_acceleration.y,
                                 z=msg.linear_acceleration.z),
        linear_acceleration_covariance=np.asarray(msg.linear_acceleration_covariance,
                                                  dtype=np.float64),
    )


def rebuild_transform(tr, ts):
    t, r = tr.transform.translation, tr.transform.rotation
    return ts.types['geometry_msgs/msg/TransformStamped'](
        header=rebuild_header(tr.header, ts),
        child_frame_id=strip(tr.child_frame_id),
        transform=ts.types['geometry_msgs/msg/Transform'](
            translation=ts.types['geometry_msgs/msg/Vector3'](x=t.x, y=t.y, z=t.z),
            rotation=ts.types['geometry_msgs/msg/Quaternion'](x=r.x, y=r.y, z=r.z, w=r.w),
        ),
    )


def rebuild_image(msg, ts, to_16uc1):
    """Optionally 32FC1 metres -> 16UC1 millimetres, matching aligned_depth_to_color."""
    if to_16uc1:
        metres = np.frombuffer(msg.data, dtype=np.float32).reshape(msg.height, msg.width)
        mm = np.nan_to_num(metres, nan=0.0, posinf=0.0, neginf=0.0) * 1000.0
        data = np.clip(mm, 0, 65535).astype(np.uint16).view(np.uint8).reshape(-1)
        encoding, step = '16UC1', msg.width * 2
    else:
        data = np.frombuffer(msg.data, dtype=np.uint8)
        encoding, step = msg.encoding, msg.step
    return ts.types['sensor_msgs/msg/Image'](
        header=rebuild_header(msg.header, ts),
        height=msg.height,
        width=msg.width,
        encoding=encoding,
        is_bigendian=msg.is_bigendian,
        step=step,
        data=data,
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--src', required=True, type=Path, help='TUM ROS 1 .bag')
    ap.add_argument('--dst', required=True, type=Path, help='output ROS 2 bag dir')
    ap.add_argument('--keep-float-depth', action='store_true',
                    help='leave depth as 32FC1 metres instead of 16UC1 mm')
    ap.add_argument('--version', type=int, default=5,
                    help='rosbag2 metadata version (5 = humble-readable)')
    args = ap.parse_args()

    if args.dst.exists():
        raise SystemExit(f'{args.dst} already exists, refusing to overwrite')

    ts = get_typestore(Stores.ROS2_HUMBLE)
    TF = ts.types['tf2_msgs/msg/TFMessage']

    static_seen: dict[tuple[str, str], object] = {}
    gt_rows: list[str] = []
    counts: dict[str, int] = {}

    with AnyReader([args.src]) as reader, Writer(args.dst, version=args.version) as writer:
        conns: dict[str, object] = {}

        def conn_for(topic: str, msgtype: str):
            if topic not in conns:
                qos = (TF_STATIC_QOS,) if topic == '/tf_static' else ()
                conns[topic] = writer.add_connection(
                    topic, msgtype, typestore=ts, offered_qos_profiles=qos)
            return conns[topic]

        for conn, stamp, raw in reader.messages():
            src_topic = conn.topic
            if src_topic not in TOPIC_MAP:
                continue
            msg = reader.deserialize(raw, conn.msgtype)

            out_type = conn.msgtype
            if src_topic == '/tf':
                dynamic = []
                for tr in msg.transforms:
                    parent, child = strip(tr.header.frame_id), strip(tr.child_frame_id)
                    out_tr = rebuild_transform(tr, ts)
                    if (parent, child) in STATIC_EDGES:
                        static_seen.setdefault((parent, child), out_tr)
                        continue
                    dynamic.append(out_tr)
                    if (parent, child) == GT_EDGE:
                        t, r = tr.transform.translation, tr.transform.rotation
                        sec = tr.header.stamp.sec + tr.header.stamp.nanosec * 1e-9
                        gt_rows.append(
                            f'{sec:.6f} {t.x:.6f} {t.y:.6f} {t.z:.6f} '
                            f'{r.x:.6f} {r.y:.6f} {r.z:.6f} {r.w:.6f}'
                        )
                if not dynamic:
                    continue
                # ROS 1 bags carry /tf as the legacy tf/tfMessage type.
                out_type = 'tf2_msgs/msg/TFMessage'
                out_msg = TF(transforms=dynamic)
            elif out_type == 'sensor_msgs/msg/CameraInfo':
                out_msg = rebuild_camera_info(msg, ts)
            elif out_type == 'sensor_msgs/msg/Imu':
                out_msg = rebuild_imu(msg, ts)
            else:
                out_msg = rebuild_image(
                    msg, ts,
                    to_16uc1=(src_topic == '/camera/depth/image'
                              and not args.keep_float_depth))

            dst_topic = TOPIC_MAP[src_topic]
            writer.write(conn_for(dst_topic, out_type), stamp,
                         ts.serialize_cdr(out_msg, out_type))
            counts[dst_topic] = counts.get(dst_topic, 0) + 1

        # Static transforms are written once, at the very start of the bag, so a
        # single `ros2 bag play` warm-up is enough to populate the tf tree.
        if static_seen:
            first_stamp = min(s for s in [reader.start_time])
            static_conn = conn_for('/tf_static', 'tf2_msgs/msg/TFMessage')
            writer.write(static_conn, first_stamp,
                         ts.serialize_cdr(TF(transforms=list(static_seen.values())),
                                          'tf2_msgs/msg/TFMessage'))
            counts['/tf_static'] = len(static_seen)

    gt_path = args.dst / 'groundtruth.tum'
    gt_path.write_text('# timestamp tx ty tz qx qy qz qw\n' + '\n'.join(gt_rows) + '\n')

    manifest = {
        'source_bag': str(args.src),
        'source_dataset': 'TUM RGB-D (cvg.cit.tum.de/rgbd)',
        'depth_encoding': '32FC1 (metres)' if args.keep_float_depth else '16UC1 (mm)',
        'topic_map': TOPIC_MAP,
        'static_tf_edges': [f'{p} -> {c}' for p, c in sorted(static_seen)],
        'groundtruth_edge': f'{GT_EDGE[0]} -> {GT_EDGE[1]}',
        'groundtruth_poses': len(gt_rows),
        'message_counts': counts,
    }
    (args.dst / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')

    print(f'wrote {args.dst}')
    for topic, n in sorted(counts.items()):
        print(f'  {topic:<52} {n}')
    print(f'  groundtruth.tum{"":<37} {len(gt_rows)} poses')


if __name__ == '__main__':
    main()
