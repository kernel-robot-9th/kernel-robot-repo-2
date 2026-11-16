#!/bin/bash
# Apply a manual exposure to the top camera AFTER LeRobot has started streaming from it.
# The SNAP U2 ignores exposure set before the stream starts (it resets on stream start),
# so this waits until the device is open, then re-applies the setting.
# Usage: ./set_top_exposure.sh 90 &      (started in the background by record/eval/teleop scripts)
VALUE=${1:?exposure value, e.g. 90}
DEV=$(readlink -f /dev/cam_top)

# Wait up to 120 s for a process to open the camera.
for _ in $(seq 1 240); do
  fuser "$DEV" >/dev/null 2>&1 && break
  sleep 0.5
done
sleep 1  # let the stream start

apply() {
  # Toggle through auto so the driver actually sends the new value to the camera.
  v4l2-ctl -d "$DEV" -c auto_exposure=3
  sleep 0.3
  v4l2-ctl -d "$DEV" -c auto_exposure=1 -c exposure_time_absolute="$VALUE"
}
apply
echo "[top cam] manual exposure ${VALUE} applied: $(v4l2-ctl -d "$DEV" -C auto_exposure,exposure_time_absolute | tr '\n' ' ')"
