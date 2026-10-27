"""Central settings for FitForm AI. Change values here instead of inside the modules."""

# ---- Camera ----
CAMERA_INDEX = 0            # used with --camera usb (first webcam); default --camera auto finds the cameras
PICAM_ROTATE = 180           # Pi (AI) camera picture rotation (180 = mounted upside down); --rotate overrides
WEBCAM_ROTATE = 0            # USB webcam picture rotation
                            # on the Pi, run with --camera picam to use the Pi Camera Module 2
CAPTURE_WIDTH = 640          # 640x480 is plenty for pose detection and much faster than 1280x720 on the Pi
CAPTURE_HEIGHT = 480
CAPTURE_FPS = 30
CAMERA_STALL_SECONDS = 3.0   # Pi camera sends no picture this long = stalled: rpicam-vid is restarted
CAMERA_MAX_RESTARTS = 20     # ... at most this often per run (then the app stops: camera really broken)
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
MIN_UP_SECONDS = 0.4         # lifting (wrist leaves the bottom -> top) faster than this = "too fast".
                             # Labelled clips 27 Oct (wrist-height timing): slow proper lifts 0.53-1.07 s,
                             # fast swings 0.29-0.50 s
MAX_UP_SECONDS = 5.0         # lifting slower than this = "too slow", rep not counted
MIN_DOWN_SECONDS = 0.55      # lowering (wrist leaves the top -> back at the bottom) faster than this = "lowered
                             # too fast": the rep is judged when the arm is back down, not at the top.
                             # 27 Oct clips: slow proper 0.63-1.49 s, swings 0.17-0.60 s, fast drops 0.30-0.48 s.
                             # 0 = no lowering check (rep counted at the top)
WRIST_MOVE_MARGIN = 0.2      # wrist this far (in shoulder widths) from its bottom / top level = it has left it
                             # (wrist height is used for the timing: from the front the forearm comes towards the
                             # camera and the 2D elbow angle only changes late in the lift, which read slow lifts
                             # as 'too fast'; the wrist's height rises steadily)
STRAIGHT_CONFIRM_FRAMES = 2  # arm must read straight this many frames in a row (ignores one-frame angle jumps)
FORESHORTEN_RATIO = 0.55     # forearm looks shorter than this share of the upper arm = pointing at the camera;
                             # those frames are not used to finish a rep (the 2D angle is unreliable then)
TOP_CONFIRM_FRAMES = 2       # arm must read curled this many frames in a row before the rep is finished
FAULT_HOLD_SECONDS = 0.3     # during the lift a fault (elbow moved, wrist bent, wrong hand, hand hidden)
                             # must last longer than this to reject the rep; shorter blips are ignored

# ---- Hand checks (MediaPipe Hands) - strict: the hand must be seen and correct, or the rep is not counted ----
FIST_CHECK = True            # hand must be a clenched fist (or wrapped round a bottle / dumbbell) during the curl
PALM_CHECK = True            # palm must face forward or towards the body; outward or backward fails
HAND_WINDOW_BEFORE = 1.0     # the down (start) position: last N seconds with the arm straight before the lift
HAND_MIN_READINGS = 2        # hand must be seen this many times in the down position, else "hand not visible"
PALM_CHECK_ELBOW_MIN = 110   # fist / hidden-hand readings count in the lower part of the rep (elbow above this angle)
PALM_DIR_ELBOW_MIN = 150     # FRONT camera palm direction only while the arm is nearly straight (above this angle);
                             # the side camera judges the middle and top of the rep
REJECT_PAUSE_SECONDS = 2.5   # after a rep is not counted: show what was wrong and what to do for this long
                             # before the next rep can start
PALM_MIN_SCORE = 0.35        # 0..1 how clearly the palm must face forward/inward to be read as good (else 'side')
PALM_BAD_MIN_SCORE = 0.55    # 0..1 a WRONG direction must be this clear, else it is read as 'side' (unclear);
                             # a fist seen from the front gives noisy palm readings, so weak 'wrong' ones are ignored
PALM_HOLD_SECONDS = 0.5      # hand turned outward/backward continuously this long during the lift = not counted
PALM_SIGN = 1                # set to -1 if the terminal shows palm 'back' when the palm faces the camera
PALM_INWARD_SIGN = 1         # set to -1 if the terminal shows 'outward' when the palm faces the body
FIST_REJECTS = False         # False = 'hand not clenched' is advice only (reported on the phone page with pictures):
                             # a hand round a bottle or dumbbell can look open to the camera (21-22 Oct tests)
HOLD_CHECK = True            # 'is there a weight in the hand?' - CNN on the front camera's hand picture
HOLD_MODEL = "models/hand_holding.onnx"   # from tools/train_hand_classifier.py (MobileNetV3-Small, ~5 ms per hand)
HOLD_EVERY_N = 3             # classify the hands every N frames
HOLD_MIN_READINGS = 3        # a rep needs this many hand readings (start position + lift) to be judged ...
HOLD_EMPTY_RATIO = 0.6       # ... and this share of them 'empty' = 'no weight' for that rep (one vote per rep,
                             # so single blurred frames do not decide it; per picture 98.5 % on a new session)
HOLD_REJECTS = False         # False = advice only (phone page, with pictures): trained on one bottle and one
                             # person so far - not reliable enough to fail a rep (no dumbbell in the data yet)
HAND_HIDDEN_REJECTS = False  # False = 'hand not visible' does not stop a rep: the hand check only serves the grip
                             # and fist direction, which are advice only. Live test 27 Oct: an empty relaxed hand
                             # 2-3 m away was often not found by MediaPipe Hands (8 of 20 proper curls rejected)
PALM_REJECTS = False         # False = palm/fist direction only gives a tip ("Keep your palm facing your body"),
                             # the rep still counts. The labelled runs of 21 Oct showed the same correct right-arm
                             # curl reading anywhere from 0 to +-1.0, so it is not reliable enough to fail a rep.
OUTWARD_PAUSE = False        # False = no pause / no on-screen warning in the session: the phone page reports
                             # the turned-out reps (with hand pictures) instead (the reading is not reliable)
PALM_TIP_ON_SCREEN = False   # tip under a counted rep when the fist looked turned out (off: shown on the phone page)
OUTWARD_WARN_MIN = 2         # phone page warns when at least this many reps looked turned out in a session
OUTWARD_STREAK = 3           # this many reps with the fist turned out (front OR side camera) ...
OUTWARD_WINDOW = 4           # ... within the last this-many reps ...
OUTWARD_PAUSE_SECONDS = 3.0  # ... pauses counting this long with 'Your fist is facing outward'
DEMO_SECONDS = 8.0           # demo animation at the start (counts down to 1; anything done during it is not
                             # counted); --no-demo turns it off
FIST_PALM_TO_BODY = True     # front camera, clenched fist: palm must face the body; turned outward OR palm
                             # forward = wrong (from the front these two look the same for a fist)
FIST_CALIB_FILE = "~/fist_calib.json"  # from tools/fist_calibrate.py (labelled runs); used when present
FIST_TURN_MIN = 0.5          # 0..1 how clear the fist reading must be (measured: about 0.8-1.0); weaker = unclear
SIDE_EVERY_N = 2             # side camera (--side-camera): judge the palm every N frames
SIDE_PALM_SIGN = -1          # flip to 1 if the side preview says 'turned out' when your palm faces your body
SIDE_PALM_MIN = 0.6          # 0..1 how clear the side reading must be; weaker = 'unclear' (not judged).
                             # High because the webcam cannot sit at a true 90 degrees yet (1 m cable)
SIDE_BAD_MIN_READINGS = 3    # side camera: at least this many 'turned out' readings in a rep ...
SIDE_BAD_RATIO = 0.5         # ... and this share of its clear readings -> rep not counted
HAND_EVERY_N = 2             # run hand detection every N frames (1 = every frame; 2 = faster)
PARALLEL_HANDS = True        # run hand detection at the same time as pose detection (uses a second CPU core)
HAND_MODEL_COMPLEXITY = 0    # 0 = fastest
HAND_MIN_CONFIDENCE = 0.4
HAND_MATCH_DIST = 0.18       # hand must be within this fraction of the frame width of the pose wrist

# ---- Screen ----
FULLSCREEN = True            # window fills the whole screen at start (no keyboard needed); --windowed turns it off
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
# ---- Sessions, summary and phone page ----
PRESENCE_VISIBILITY = 0.5    # both shoulders must be seen at least this clearly to count as 'someone is there'
END_AWAY_SECONDS = 5.0       # session ends when nobody is seen for this long ...
END_IDLE_SECONDS = 30.0      # ... or no curl is finished for this long (after at least one curl)
AWAY_GRACE_SECONDS = 1.0     # 'Saving session in ...' only once nobody has been seen this long (not while you
                             # are there - before 27 Oct it showed during the whole session) ...
IDLE_WARN_SECONDS = 10.0     # ... or in the last this-many seconds of END_IDLE_SECONDS without a curl
SAVED_BANNER_SECONDS = 12.0  # 'Session saved - open ... on your phone' stays on screen this long
DEVICE_LOGIN_MINUTES = 10    # 'Start on this device' from the phone is valid this long if no session starts
REQUIRE_LOGIN = True         # curls only count after someone taps 'Train on this device' (no guest sessions);
                             # ignored with --no-server or --video, where nobody can log in
MAX_SNAPSHOTS = 6            # hand pictures kept per session for the turned-out-fist warning
LOG_DIR = "logs"
CSV_FILENAME = "sessions.csv"
FLASK_ENABLED = True
FLASK_HOST = "0.0.0.0"       # reachable from other devices on the same Wi-Fi
FLASK_PORT = 5000
