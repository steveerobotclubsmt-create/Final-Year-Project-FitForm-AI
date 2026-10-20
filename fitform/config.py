"""Central settings for FitForm AI. Change values here instead of inside the modules."""

# ---- Camera ----
CAMERA_INDEX = 0            # 0 = default webcam; try 1 if the wrong camera opens
                            # on the Pi, run with --camera picam to use the Pi Camera Module 2
CAPTURE_WIDTH = 1280
CAPTURE_HEIGHT = 720
DISPLAY_WIDTH = 960          # each camera view is resized to this before display
DISPLAY_HEIGHT = 540

# ---- MediaPipe Pose ----
MIN_DETECTION_CONFIDENCE = 0.7
MIN_TRACKING_CONFIDENCE = 0.7
MODEL_COMPLEXITY = 1         # 0 = fastest (good for Pi 5), 1 = balanced, 2 = most accurate
LANDMARK_VISIBILITY_MIN = 0.6

# ---- Bicep curl thresholds (degrees) ----
DOWN_ANGLE = 150             # elbow angle above this = arm extended (bottom of rep); 2D straight arm reads ~155-180
UP_ANGLE = 60                # elbow angle below this = arm curled (top of rep); 2D full curl reads ~10-50
EXTENSION_MIN_ANGLE = 140    # hint 'Extend arm fully!' when lowering stops short of this
UPPER_ARM_DRIFT_MAX = 30     # upper arm may move this many degrees from its start position before 'elbow moved'
WRIST_STRAIGHT_MIN = 145     # elbow-wrist-knuckle angle below this = wrist bent (needs the hand to be seen)
SMOOTHING_ALPHA = 0.6        # 1.0 = no smoothing; lower = smoother but slower to react
USE_3D_ANGLES = False        # False = 2D image angles (tested on the Pi 20 Oct: 2D straight ~160-180, curled ~10-50;
                             # 3D only ~140-165 straight and ~70-100 curled, too compressed to count reps)
                             # override at run time with --angles 2d / --angles 3d

# ---- Rep quality ----
READY_HOLD_SECONDS = 0.5     # before the first rep (or after the arm left the view) hold the arm straight this long
ARM_LOST_RESET_SECONDS = 2.0 # arm out of view longer than this -> must show the ready position again
MIN_UP_SECONDS = 0.6         # lifting (straight -> top) faster than this = "too fast", rep not counted
MAX_UP_SECONDS = 5.0         # lifting slower than this = "too slow", rep not counted

# ---- Hand checks (MediaPipe Hands) - strict: the hand must be seen and correct, or the rep is not counted ----
FIST_CHECK = True            # hand must be a clenched fist (or wrapped round a bottle / dumbbell) during the curl
PALM_CHECK = True            # standard curl: palm faces the camera at the bottom of the curl
HAND_WINDOW_BEFORE = 1.0     # seconds before the lift starts that are also checked (the start position)
HAND_MIN_READINGS = 2        # hand must be seen in at least this many checked frames, else "show your hand"
PALM_CHECK_ELBOW_MIN = 110   # palm direction is judged only in the lower part of the rep (elbow above this angle)
PALM_MIN_SCORE = 0.35        # 0..1 how clearly the palm must face the camera to count as 'front'
PALM_SIGN = 1                # set to -1 if the terminal shows palm 'back' when the palm faces the camera
HAND_EVERY_N = 1             # run hand detection every N frames (1 = every frame; 2 = faster but fewer readings)
HAND_MODEL_COMPLEXITY = 0    # 0 = fastest
HAND_MIN_CONFIDENCE = 0.5
HAND_MATCH_DIST = 0.12       # hand must be within this fraction of the frame width of the pose wrist

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
