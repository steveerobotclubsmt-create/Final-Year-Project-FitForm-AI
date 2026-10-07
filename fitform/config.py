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
DOWN_ANGLE = 145             # elbow angle above this = arm extended (bottom of rep); a straight arm reads ~150-160
UP_ANGLE = 60                # elbow angle below this = arm curled (top of rep)
EXTENSION_MIN_ANGLE = 140    # hint 'Extend arm fully!' when lowering stops short of this
UPPER_ARM_DRIFT_MAX = 25     # upper arm may move this many degrees from its start position before 'elbow moved'
WRIST_STRAIGHT_MIN = 145     # elbow-wrist-knuckle angle below this = wrist bent (needs the hand to be seen)
SMOOTHING_ALPHA = 0.6        # 1.0 = no smoothing; lower = smoother but slower to react
USE_3D_ANGLES = True         # use MediaPipe 3D world landmarks (works from the front or the side)

# ---- Hand / fist check (MediaPipe Hands) ----
FIST_CHECK = True            # a rep only counts if the hand is a fist (holding the dumbbell)
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
