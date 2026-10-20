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

# ---- Palm direction (standard curl: palm faces the camera / front at the bottom of the curl) ----
PALM_CHECK = True            # reject a rep done with the back of the hand to the front (reverse grip)
PALM_CHECK_ELBOW_MIN = 120   # palm is judged only in the lower part of the rep (elbow above this angle)
PALM_MIN_SCORE = 0.3         # 0..1 how clearly the palm must face front/back to be counted as a reading
PALM_AWAY_MIN_FRAMES = 2     # 'away' readings needed (and more than 'front' readings) to reject a rep
PALM_SIGN = 1                # set to -1 if the debug view shows FRONT when the back of the hand faces the camera

# ---- Hand / fist check (MediaPipe Hands) ----
FIST_CHECK = False           # True = a rep only counts if the hand is a clenched fist (not required)
FIST_STRICT = False          # False: a hand that can't be seen (hidden by the dumbbell) is not penalised
OPEN_PALM_MIN_FRAMES = 2     # open palm must be seen in at least this many checked frames to reject a rep
HAND_EVERY_N = 2             # run hand detection every N frames (higher = faster FPS on the Pi)
HAND_MODEL_COMPLEXITY = 0    # 0 = fastest
HAND_MIN_CONFIDENCE = 0.5
HAND_MATCH_DIST = 0.12       # hand must be within this fraction of the frame width of the pose wrist


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
