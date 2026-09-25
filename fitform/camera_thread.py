"""Reads a camera (or video file) in a background thread so the main loop always
gets the newest frame instead of waiting on a buffered one."""

import threading
import time

import cv2


class CameraStream:
    def __init__(self, source, width=None, height=None):
        self.source = source
        self.is_file = isinstance(source, str)
        self.cap = cv2.VideoCapture(source)
        if not self.is_file:
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
        return self

    def _update(self):
        # Video files are paced at their own frame rate; live cameras run as fast as they deliver.
        delay = 0.0
        if self.is_file:
            fps = self.cap.get(cv2.CAP_PROP_FPS) or 30
            delay = 1.0 / fps
        while self._running:
            ok, frame = self.cap.read()
            if not ok:
                if self.is_file:
                    self.finished = True
                    break
                time.sleep(0.01)
                continue
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
        if self._thread is not None:
            self._thread.join(timeout=1.0)
        self.cap.release()
