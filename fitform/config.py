"""Central settings for FitForm AI. Change values here instead of inside the modules."""

# ---- Camera ----
CAMERA_INDEX = 0            # 0 = default webcam; try 1 if the wrong camera opens
                            # on the Pi, run with --camera picam to use the Pi Camera Module 2
CAPTURE_WIDTH = 640          # 640x480 is plenty for pose detection and much faster than 1280x720 on the Pi
CAPTURE_HEIGHT = 480
CAPTURE_FPS = 30
CAPTURE_MJPG = True          # ask a USB camera for MJPG (USB 2.0 cameras are often limited to ~5-10 fps raw)
DISPLAY_WIDTH = 800          # processing + display size; keep the same 4:3 shape as the camera so angles are true
DISPLAY_HEIGHT = 600

# ---- MediaPipe Pose ----
MIN_DETECTION_CONFIDENCE = 0.7
MIN_TRACKING_CONFIDENCE = 0.7
MODEL_COMPLEXITY = 0         # 0 = fastest (used on the Pi 5), 1 = balanced, 2 = most accurate
LANDMARK_VISIBILITY_MIN = 0.6

# ---- Bicep curl thresholds (degrees) ----
DOWN_ANGLE = 150             # elbow angle above this = arm extended (bottom of rep); 2D straight arm reads ~155-180
REARM_ANGLE = 140            # after the first rep, the next rep starts once the arm is back above this angle
                             # (when doing reps back to back the arm often only reaches ~140-150, tested 20 Oct)
UP_ANGLE = 60                # elbow angle below this = arm curled (top of rep); 2D full curl reads ~10-50
EXTENSION_MIN_ANGLE = 140    # hint 'Extend arm fully!' when lowering stops short of this
UPPER_ARM_DRIFT_MAX = 30     # upper arm may move this many degrees from its start position before 'elbow moved'
UPPER_ARM_MAX_TILT = 30      # upper arm must point down: more than this many degrees from vertical = wrong
UPPER_ARM_MIN_LENGTH = 0.8   # elbow forward/back: the upper arm looks shorter to a front camera; below this
                             # share of its length at the start (measured against shoulder width) = wrong
SIDE_VIEW_RATIO = 0.45       # shoulder width / torso length below this = standing sideways to the camera
                             # (then the forward/back check is skipped; the upper-arm tilt check covers it)
PALM_BAD_MAX_RATIO = 0.4     # down position + lower part of the lift: this share (or more) of wrong palm
                             # readings = rep not counted ('side' / unclear readings are not counted either way)
PALM_BAD_MIN_READINGS = 2    # ... and at least this many wrong readings
WRIST_STRAIGHT_MIN = 145     # elbow-wrist-knuckle angle below this = wrist bent (needs the hand to be seen)
SMOOTHING_ALPHA = 0.6        # 1.0 = no smoothing; lower = smoother but slower to react
USE_3D_ANGLES = False        # False = 2D image angles (tested on the Pi 20 Oct: 2D straight ~160-180, curled ~10-50;
                             # 3D only ~140-165 straight and ~70-100 curled, too compressed to count reps)
                             # override at run time with --angles 2d / --angles 3d

# ---- Rep quality ----
READY_HOLD_SECONDS = 0.5     # before the first rep (or after the arm left the view) hold the arm straight this long
ARM_LOST_RESET_SECONDS = 2.0 # arm out of view longer than this -> must show the ready position again
MIN_UP_SECONDS = 0.4         # lifting (straight -> top) faster than this = "too fast" (normal reps measured 0.5-0.9 s)
MAX_UP_SECONDS = 5.0         # lifting slower than this = "too slow", rep not counted
STRAIGHT_CONFIRM_FRAMES = 2  # arm must read straight this many frames in a row (ignores one-frame angle jumps)
TOP_CONFIRM_FRAMES = 2       # arm must read curled this many frames in a row before the rep is finished
FAULT_HOLD_SECONDS = 0.3     # during the lift a fault (elbow moved, wrist bent, wrong hand, hand hidden)
                             # must last longer than this to reject the rep; shorter blips are ignored

# ---- Hand checks (MediaPipe Hands) - strict: the hand must be seen and correct, or the rep is not counted ----
FIST_CHECK = True            # hand must be a clenched fist (or wrapped round a bottle / dumbbell) during the curl
PALM_CHECK = True            # palm must face forward or towards the body; outward or backward fails
HAND_WINDOW_BEFORE = 1.0     # the down (start) position: last N seconds with the arm straight before the lift
HAND_MIN_READINGS = 2        # hand must be seen this many times in the down position, else "hand not visible"
PALM_CHECK_ELBOW_MIN = 110   # palm direction is judged only in the lower part of the rep (elbow above this angle)
PALM_MIN_SCORE = 0.35        # 0..1 how clearly the palm must face forward/inward to be read as good (else 'side')
PALM_BAD_MIN_SCORE = 0.55    # 0..1 a WRONG direction must be this clear, else it is read as 'side' (unclear);
                             # a fist seen from the front gives noisy palm readings, so weak 'wrong' ones are ignored
PALM_HOLD_SECONDS = 0.5      # hand turned outward/backward continuously this long during the lift = not counted
PALM_CALIB_FILE = "~/palm_calib.csv"   # from tools/palm_calibrate.py; used for the palm direction when present
PALM_CALIB_MARGIN = 0.5      # readings about equally close to a good and a wrong position are 'unclear'
PALM_SIGN = 1                # set to -1 if the terminal shows palm 'back' when the palm faces the camera
PALM_INWARD_SIGN = 1         # set to -1 if the terminal shows 'outward' when the palm faces the body
HAND_EVERY_N = 2             # run hand detection every N frames (1 = every frame; 2 = faster)
PARALLEL_HANDS = True        # run hand detection at the same time as pose detection (uses a second CPU core)
HAND_MODEL_COMPLEXITY = 0    # 0 = fastest
HAND_MIN_CONFIDENCE = 0.4
HAND_MATCH_DIST = 0.18       # hand must be within this fraction of the frame width of the pose wrist

# ---- Screen ----
MESSAGE_HOLD_SECONDS = 1.0   # a feedback message stays at least this long (stops the text flickering)


# ---- Calories ----
USER_WEIGHT_KG = 70.0
MET_BICEP_CURL = 3.5         # moderate resistance training

# ---- Raspberry Pi GPIO (BCM pin numbers) ----
GPIO_ENABLED = True          # falls back to "no hardware" automatically on a laptop
GREEN_LED_PIN = 17
RED_LED_PIN = 27
BUZZER_PIN = 22
BUZZER_BEEP_SECONDS = 0.1

# ---- Session logging / Flask ----
LOG_DIR = "logs"
CSV_FILENAME = "sessions.csv"
FLASK_ENABLED = True
FLASK_HOST = "0.0.0.0"       # reachable from other devices on the same Wi-Fi
FLASK_PORT = 5000
