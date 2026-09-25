"""Central settings for FitForm AI. Change values here instead of inside the modules."""

# ---- Camera ----
CAMERA_INDEX = 0            # 0 = default webcam; try 1 if the wrong camera opens
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
DOWN_ANGLE = 155             # elbow angle above this = arm extended (bottom of rep)
UP_ANGLE = 50                # elbow angle below this = arm curled (top of rep)
EXTENSION_MIN_ANGLE = 145    # when "down", elbow must stay above this
TORSO_SWING_MAX = 35         # elbow-shoulder-hip angle above this = elbow swinging
WRIST_STRAIGHT_MIN = 150     # elbow-wrist-index angle below this = wrist bent
SMOOTHING_ALPHA = 0.6        # 1.0 = no smoothing; lower = smoother but slower to react


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
