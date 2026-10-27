"""Reads a camera (or video file) in a background thread so the main loop always
gets the newest frame instead of waiting on a buffered one.

Sources:
  - an int (0, 1, ...)  -> USB webcam / laptop camera through OpenCV
  - "picam"             -> Raspberry Pi Camera Module (CSI) through the `rpicam-vid` command.
                           This works from any Python version (e.g. a Python 3.12 venv on
                           Raspberry Pi OS Trixie), because it does not need Picamera2.
  - any other string    -> path to a video file
"""

import shutil
import subprocess
import threading
import time

import cv2

from . import config
import numpy as np


class _RpicamCapture:
    """Minimal cv2.VideoCapture-like wrapper around `rpicam-vid` raw YUV420 output."""

    def __init__(self, width, height, fps=30):
        # rpicam-vid pads YUV rows; widths that are a multiple of 64 avoid padding
        # (1280x720 and 640x480 are both safe).
        self.width = int(width or 1280)
        self.height = int(height or 720)
        self.frame_bytes = self.width * self.height * 3 // 2
        self.proc = None
        exe = shutil.which("rpicam-vid") or shutil.which("libcamera-vid")
        if exe is None:
            return
        cmd = [exe, "-t", "0", "-n", "--codec", "yuv420",
               "--width", str(self.width), "--height", str(self.height),
               "--framerate", str(fps), "-o", "-"]
        try:
            self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                         bufsize=self.frame_bytes)
        except OSError:
            self.proc = None

    def isOpened(self):
        return self.proc is not None and self.proc.poll() is None

    def read(self):
        proc = self.proc                    # (release() from the watchdog thread may clear self.proc meanwhile)
        if proc is None or proc.poll() is not None:
            return False, None
        buf = bytearray()
        while len(buf) < self.frame_bytes:
            try:
                chunk = proc.stdout.read(self.frame_bytes - len(buf))
            except (ValueError, OSError):   # pipe closed by release()
                return False, None
            if not chunk:
                return False, None
            buf.extend(chunk)
        yuv = np.frombuffer(bytes(buf), dtype=np.uint8).reshape(self.height * 3 // 2, self.width)
        return True, cv2.cvtColor(yuv, cv2.COLOR_YUV2BGR_I420)

    def get(self, prop):
        return 0

    def set(self, prop, value):
        return False

    def release(self):
        if self.proc is not None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.proc.kill()
            self.proc = None


class CameraStream:
    def __init__(self, source, width=None, height=None):
        self.source = source
        self.is_picam = source == "picam"
        self.is_file = isinstance(source, str) and not self.is_picam
        self._size = (width, height)
        self._last_frame_t = time.time()
        self.restarts = 0
        if self.is_picam:
            self.cap = _RpicamCapture(width, height)
        else:
            self.cap = cv2.VideoCapture(source)
            if not self.is_file:
                if getattr(config, "CAPTURE_MJPG", False):
                    self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
                if getattr(config, "CAPTURE_FPS", None):
                    self.cap.set(cv2.CAP_PROP_FPS, config.CAPTURE_FPS)
                if width:
                    self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
                if height:
                    self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
                self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        self._frame = None
        self._frame_id = 0
        self._lock = threading.Lock()
        self._running = False
        self._thread = None
        self.finished = False  # True when a video file reaches its end

    def is_opened(self):
        return self.cap.isOpened()

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._update, daemon=True)
        self._thread.start()
        if self.is_picam:
            threading.Thread(target=self._watchdog, daemon=True).start()
        return self

    def _watchdog(self):
        """The Pi camera sometimes stops sending pictures while rpicam-vid keeps running (27 Oct: the app froze
        mid-session, Pi at 77 C and throttled). No picture for CAMERA_STALL_SECONDS: stop rpicam-vid, which
        ends the pipe read in _update, and _update starts a new one."""
        while self._running:
            time.sleep(0.5)
            if self._running and time.time() - self._last_frame_t > config.CAMERA_STALL_SECONDS:
                print(f"[CAMERA] no picture for {config.CAMERA_STALL_SECONDS:.0f} s - restarting the Pi camera")
                self._last_frame_t = time.time()       # give the new process time to start
                self.cap.release()

    def _update(self):
        # Video files are paced at their own frame rate; live cameras run as fast as they deliver.
        delay = 0.0
        if self.is_file:
            fps = self.cap.get(cv2.CAP_PROP_FPS) or 30
            delay = 1.0 / fps
        while self._running:
            ok, frame = self.cap.read()
            if not ok:
                if self.is_picam and self._running and self.restarts < config.CAMERA_MAX_RESTARTS:
                    self.cap.release()                 # stalled (watchdog) or crashed: start rpicam-vid again
                    self.restarts += 1
                    time.sleep(0.5)
                    self.cap = _RpicamCapture(*self._size)
                    self._last_frame_t = time.time()
                    continue
                if self.is_file or (self.is_picam and not self.cap.isOpened()):
                    self.finished = True
                    break
                time.sleep(0.01)
                continue
            self._last_frame_t = time.time()
            with self._lock:
                self._frame = frame
                self._frame_id += 1
            if delay:
                time.sleep(delay)

    def read(self):
        """Returns (frame_id, frame). frame is None until the first frame arrives."""
        with self._lock:
            if self._frame is None:
                return self._frame_id, None
            return self._frame_id, self._frame.copy()

    def stop(self):
        self._running = False
        if self.is_picam:
            self.cap.release()  # unblocks the pipe read in the thread
        if self._thread is not None:
            self._thread.join(timeout=1.0)
        self.cap.release()
