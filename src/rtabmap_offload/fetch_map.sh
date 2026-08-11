#!/usr/bin/env bash
# Copy RTAB-Map databases off the k8s PVC onto this machine.
#
#   ./fetch_map.sh                  # list what is on the volume
#   ./fetch_map.sh latest           # pull the newest .db
#   ./fetch_map.sh rtabmap_20260811-061430.db
#   OUT=~/maps ./fetch_map.sh latest
#
# RTAB-Map writes its working memory out on SIGTERM, so a database is only
# complete after the pod has been stopped. The intended cycle is:
#
#   kubectl scale deploy/rtabmap-offload -n hsrn-robot --replicas=0   # flush
#   kubectl scale deploy/rtabmap-offload -n hsrn-robot --replicas=1   # new run_id
#   ./fetch_map.sh latest                                            # pull run N
#
# That works because each start picks a new run_id, so bringing the pod back up
# never touches the previous run's file.
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
  echo "The PVC is only reachable through a pod; scale back up to copy:" >&2
  echo "  kubectl scale deploy/rtabmap-offload -n $NS --replicas=1" >&2
  exit 1
fi

if [[ $# -eq 0 ]]; then
  echo "pod: $POD"
  echo "databases on $DB_DIR:"
  kubectl exec -n "$NS" "$POD" -- sh -c "ls -lht $DB_DIR/*.db 2>/dev/null || echo '  (none yet)'"
  echo
  echo "pull one with: $0 <name>   |   $0 latest"
  exit 0
fi

NAME="$1"
if [[ "$NAME" == "latest" ]]; then
  NAME="$(kubectl exec -n "$NS" "$POD" -- \
            sh -c "ls -t $DB_DIR/*.db 2>/dev/null | head -1 | xargs -r basename")"
  [[ -n "$NAME" ]] || { echo "no .db files in $DB_DIR yet" >&2; exit 1; }
  echo "latest -> $NAME"
fi

mkdir -p "$OUT"
echo "copying $POD:$DB_DIR/$NAME -> $OUT/$NAME"
kubectl cp -n "$NS" "$POD:$DB_DIR/$NAME" "$OUT/$NAME"

ls -lh "$OUT/$NAME"
echo
echo "inspect with:  rtabmap-databaseViewer $OUT/$NAME"
