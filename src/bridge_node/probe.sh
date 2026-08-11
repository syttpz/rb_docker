#!/usr/bin/env bash
# Minimal Corelink reachability probe: one tiny std_msgs/String, this machine
# -> Corelink -> the k8s pod. Answers "does the data plane reach the pod at
# all" without a bag, without rtabmap, and without touching the deployment.
#
# Run the RECEIVER in the pod first (the script prints the exact command), then
# this here:
#
#   ./probe.sh udp                 # A: publish ~5 s after the receiver is up
#   DELAY=60 ./probe.sh udp probe_udp_b   # B: publish 60 s after
#   ./probe.sh tcp
#   ./probe.sh ws
#
# A works but B does not => the receiver's NAT mapping expires before data
# arrives (nf_conntrack_udp_timeout is 30 s for an unreplied flow, and
# corelink_client.hpp punches the hole with exactly one empty packet at
# on_init and never again). Both failing => the data plane never reaches the
# pod at all and the timeout theory is wrong.
#
# Each run needs its OWN topic name: the topic name is the Corelink
# stream_type, so reusing it lets a stale stream from a previous attempt
# answer for the current one.
set -eo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN="$HERE/build/ros2_bridge_node"

PROTO="${1:-udp}"
TOPIC="/${2:-probe_$PROTO}"
DELAY="${DELAY:-5}"
COUNT="${COUNT:-30}"
# WAIT=0 flips the order: start the sender first and stream continuously, then
# bring the receiver up in the pod. The gap between the receiver's single
# hole-punch and the first inbound packet is then ~1 s instead of however long
# it takes a human to switch terminals -- which is what made the
# receiver-first runs inconclusive.
WAIT="${WAIT:-1}"

case "$PROTO" in udp|tcp|ws) ;; *) echo "protocol must be udp|tcp|ws" >&2; exit 1;; esac
[[ -x "$BIN" ]] || { echo "missing $BIN -- run ./build.sh" >&2; exit 1; }

source /opt/ros/humble/setup.bash
set -u

cat <<EOF
================================================================
 Receiver command for the pod ($([ "$WAIT" = 1 ] && echo "run it FIRST" || echo "run it once this side is publishing")):

   kubectl exec -it -n hsrn-robot \$POD -- bash
   ros2 run ros2_bridge_node ros2_bridge_node --ros-args \\
       -r __node:=probe_rx \\
       -p topic.name:=$TOPIC \\
       -p topic.type:=std_msgs/msg/String \\
       -p topic.direction:=from_corelink \\
       -p corelink.data_protocol:=$PROTO
================================================================
EOF

if [[ "$WAIT" == 1 ]]; then
  read -r -p "receiver up in the pod? [enter] "
fi

pids=()
cleanup() {
  trap - EXIT INT TERM
  [[ ${#pids[@]} -gt 0 ]] && kill "${pids[@]}" 2>/dev/null || true
  wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo "[probe] sender: $TOPIC over $PROTO"
"$BIN" --ros-args \
    -r __node:=probe_tx \
    -p topic.name:="$TOPIC" \
    -p topic.type:=std_msgs/msg/String \
    -p topic.direction:=to_corelink \
    -p corelink.data_protocol:="$PROTO" &
pids+=($!)

echo "[probe] waiting ${DELAY}s before the first message"
sleep "$DELAY"

echo "[probe] publishing $COUNT messages at 1 Hz"
# --once per message rather than -r 1, so the sender logs one clearly
# attributable "Local message ... -> 1 fragment(s)" per second.
for i in $(seq 1 "$COUNT"); do
  ros2 topic pub --once "$TOPIC" std_msgs/msg/String \
      "{data: 'probe $PROTO $i'}" >/dev/null
  sleep 1
done

echo "[probe] done -- $COUNT sent. Check the pod for 'Reassembled' lines."
