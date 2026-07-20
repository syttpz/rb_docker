#!/bin/bash

set -e

# check kernel includes realsense string
if modinfo uvcvideo | grep "version:" | grep "realsense"; then 
    echo "[librealsense] Kernel updated"
else
    echo "[librealsense] Kernel update failed, exiting..."
    exit 1
fi