"""Daybook Ko‘z agent."""

import os as _os

# Before OpenCV loads: its own logging and FFmpeg's go straight to stderr, past the masking of
# URLs in our logs, so keep them quiet; RTSP is read over TCP.
_os.environ.setdefault("OPENCV_LOG_LEVEL", "ERROR")
_os.environ.setdefault("OPENCV_FFMPEG_LOGLEVEL", "-8")
_os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp")

__version__ = "0.1.0"
