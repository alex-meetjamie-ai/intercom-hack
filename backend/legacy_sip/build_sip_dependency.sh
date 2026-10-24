#!/usr/bin/env bash
# Reproducible macOS/Linux loopback-lab build; no system-wide PJSIP install.
set -euo pipefail
project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
python_bin="${PYTHON_BIN:-$project_dir/.venv/bin/python}"
source_dir="${PJSIP_SOURCE_DIR:-$project_dir/../../work/pjproject-2.17}"
commit=5a457451fa2712ba18e12b01738e8ff3af2b26fd
command -v swig >/dev/null || { echo 'Install SWIG first (macOS: brew install swig).' >&2; exit 1; }
command -v make >/dev/null
"$python_bin" -m pip install setuptools==84.2.1 wheel==0.48.0
if [[ ! -d "$source_dir" ]]; then
    git clone --depth 1 --branch 2.17 https://github.com/pjsip/pjproject.git "$source_dir"
fi
[[ "$(git -C "$source_dir" rev-parse HEAD)" == "$commit" ]] || {
    echo 'PJSIP source does not match the reviewed 2.17 commit.' >&2; exit 1;
}
cd "$source_dir"
# This build deliberately has no SIP TLS, physical audio or video support.
# Only use it with the loopback-only runtime in this project.
./configure --disable-video --disable-sound --disable-ffmpeg --disable-v4l2 \
    --disable-openh264 --disable-libyuv --disable-libwebrtc --disable-ssl \
    CFLAGS=-fPIC CXXFLAGS=-fPIC > configure-lab.log 2>&1
make dep > build-lab.log 2>&1
make -j4 >> build-lab.log 2>&1
cd pjsip-apps/src/swig/python
make PYTHON_EXE="$python_bin" > python-build-lab.log 2>&1
"$python_bin" -m pip install --no-build-isolation .
"$python_bin" -c 'import pjsua2; print("PJSUA2 imported successfully")'
