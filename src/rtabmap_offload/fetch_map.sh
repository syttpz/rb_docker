#!/usr/bin/env bash
set -eo pipefail

NS="${NS:-hsrn-robot}"
SELECTOR="${SELECTOR:-app=rtabmap-offload}"
DB_DIR="${DB_DIR:-/root/.ros}"
OUT="${OUT:-.}"

set -u

POD="$(kubectl get pod -n "$NS" -l "$SELECTOR" \
        -o jsonpath='{.items[?(@.status.phase=="Running")].metadata.name}' \
      | awk '{print $1}')"

if [[ -z "$POD" ]]; then
  echo "no Running pod for -l $SELECTOR in namespace $NS." >&2
  echo "The PVC is only reachable through a pod:" >&2
  echo "  kubectl scale deploy/rtabmap-offload -n $NS --replicas=1" >&2
  exit 1
fi

# `ros2` needs the workspace sourced, and `bash -lc` does NOT do it: a login
# shell reads ~/.bash_profile / ~/.profile, while the Dockerfile only appends
# the source lines to ~/.bashrc (which login shells skip). Source both setup
# files explicitly instead of relying on any dotfile.
ROS_SETUP="${ROS_SETUP:-/opt/ros/humble/setup.bash}"
WS_SETUP="${WS_SETUP:-/ros_ws/install/setup.bash}"
in_pod() {
  kubectl exec -n "$NS" "$POD" -- bash -c \
      "source '$ROS_SETUP'; if [ -f '$WS_SETUP' ]; then source '$WS_SETUP'; fi; $1"
}

pull() {
  local remote="$1" local_name="$2"
  mkdir -p "$OUT"
  echo "copying $POD:$remote -> $OUT/$local_name"
  kubectl cp -n "$NS" "$POD:$remote" "$OUT/$local_name"
  ls -lh "$OUT/$local_name"
  echo
  echo "inspect with:  rtabmap-databaseViewer $OUT/$local_name"
}

case "${1:-list}" in
  list)
    echo "pod: $POD"
    in_pod "ls -lht $DB_DIR/*.db $DB_DIR/*.db.back 2>/dev/null || echo '  (none yet)'"
    echo
    echo "flush + copy the running map with: $0 save"
    ;;

  save)
    # Ask the node itself rather than guessing, since run_id decides the name.
    DB="$(in_pod 'ros2 param get /rtabmap database_path' | sed -n 's/^String value is: //p')"
    [[ -n "$DB" ]] || { echo "could not read database_path from /rtabmap" >&2; exit 1; }
    echo "active database: $DB"

    in_pod 'ros2 service call /rtabmap/backup std_srvs/srv/Empty' >/dev/null
    echo "backup done (working memory flushed)"

    pull "${DB}.back" "$(basename "$DB")"
    ;;

  *)
    NAME="$1"
    pull "$DB_DIR/$NAME" "$NAME"
    ;;
esac
