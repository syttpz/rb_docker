# Test datasets

Replayable RGB-D bags for exercising the Corelink bridge and the RTAB-Map
offload pipeline without the robot or the RealSense attached.

The bags are **gitignored** (multi-GB). Reproduce them with:

```bash
./datasets/fetch_tum.sh                  # fr1_desk + fr3_long_office
./datasets/fetch_tum.sh fr1_room         # any single sequence
```

## What is here

| Path | What it is |
|---|---|
| `fetch_tum.sh` | download + convert, idempotent |
| `prepare_tum_ros2.py` | the ROS 1 -> ROS 2 rewrite (see below) |
| `ros1/*.bag` | untouched TUM downloads, keep as the immutable original |
| `<name>_rs/` | ROS 2 bag with our topic names, plus `manifest.json` and `groundtruth.tum` |

## Source: TUM RGB-D

<https://cvg.cit.tum.de/rgbd/dataset/> -- direct HTTP, no registration, CC-BY 3.0.
Kinect v1, 640x480, ~30 Hz, with mocap ground-truth poses.

| Sequence | Duration | ROS 1 size | Why |
|---|---:|---:|---|
| `fr1_desk` | 24 s | 372 MB | pipeline smoke test, has loop closures |
| `fr3_long_office` | 87 s | 1.6 GB | main run: long trajectory, large loop closure |
| `fr1_room` | 49 s | 846 MB | optional, whole-room loop |
| `fr2_pioneer_slam` | 156 s | 1.8 GB | optional, camera on a wheeled robot |

Why this one and not something closer to our hardware: it is the only RGB-D
benchmark with mocap ground truth that downloads without a registration form,
and the raw RGB frame is `rgb8` 640x480 = **921,600 bytes** -- exactly the
921 KB / 58-fragment case the fragmentation math in
`md/thesis-research-plan.md` (RQ2) is written around.

If you want a dataset recorded on an actual D435i with wheel odometry, use
[OpenLORIS-Scene](https://lifelong-robotic-vision.github.io/dataset/scene.html).
It ships aligned depth, raw depth, `/odom` and ground truth -- but it is behind
a registration form, so it has to be fetched by hand.

## What `prepare_tum_ros2.py` changes

The raw TUM bags are ROS 1 and are *not* drop-in for this stack. The script
rewrites, in one pass:

1. **frame_ids** -- strips the leading `/` (`/openni_rgb_optical_frame` ->
   `openni_rgb_optical_frame`). tf2 in ROS 2 rejects the slashed form.
2. **Topic names** -> the RealSense names the bridge and rtabmap configs use:

   | TUM | ours |
   |---|---|
   | `/camera/rgb/image_color` | `/camera/camera/color/image_raw` |
   | `/camera/rgb/camera_info` | `/camera/camera/color/camera_info` |
   | `/camera/depth/image` | `/camera/camera/aligned_depth_to_color/image_raw` |
   | `/camera/depth/camera_info` | `/camera/camera/aligned_depth_to_color/camera_info` |

3. **Depth encoding** -- `32FC1` metres -> `16UC1` millimetres, matching what
   the RealSense actually publishes. This halves the payload (1,228,800 ->
   614,400 bytes) and it is the layout the zstd-on-depth profiling assumes.
   Pass `--keep-float-depth` to skip.
4. **`/tf_static`** -- TUM puts every transform on `/tf`. The rigid camera
   chain is split out into `/tf_static`, written once at the head of the bag
   with **transient_local** durability so late subscribers still get it.
5. **`groundtruth.tum`** -- the mocap `world -> kinect` transform, dumped as
   `timestamp tx ty tz qx qy qz qw` for ATE tooling (`evo_ape tum ...`).
   It stays on `/tf` in the bag as well.

`manifest.json` records the mapping and per-topic counts for each output bag.

## Caveats

- Depth is already registered to the RGB frame by the OpenNI driver, so it is
  equivalent to `aligned_depth_to_color`, but it is Kinect v1 structured light,
  not D435i stereo -- the noise characteristics differ.
- **There is no `/odom`.** Run RTAB-Map with visual odometry
  (`rtabmap_odom/rgbd_odometry`), which is the standard way TUM is evaluated.
- No `/battery_state`, no `/cmd_vel`. Power numbers still have to come from a
  real run on the Pi.
- `fr1_desk` is handheld and fast; if visual odometry loses track, that is the
  sequence, not the pipeline.

## Playing

```bash
source /opt/ros/humble/setup.bash
ros2 bag play datasets/fr1_desk_rs --clock          # add --rate 0.5 if VO struggles
```

Everything downstream must run with `use_sim_time:=true`.
