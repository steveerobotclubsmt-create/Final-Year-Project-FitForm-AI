# FitForm AI - Pose-Based Personal Trainer

**Project videos:** see [VIDEOS.md](VIDEOS.md)

Project documents (Gantt chart, figures, photos, phone app screenshots): [docs/](docs/README.md)

Individual Major Project (6FTC2062), BEng Robotics and Artificial Intelligence, University of Hertfordshire.

FitForm AI runs MediaPipe Pose and Hands (pre-trained CNNs), its own fine-tuned CNN (MobileNetV3-Small, "weight in hand?") and OpenCV on a Raspberry Pi 5 with the Raspberry Pi AI Camera, all offline. It counts bicep curl repetitions per arm and checks exercise form in real time, gives feedback on a 7-inch touch display (green/red form status, why a curl was not counted and how to fix it) and through spoken feedback on a Bluetooth speaker, and saves every session to the user's account. On a phone on the same Wi-Fi, the user logs in with a QR code and sees the session summary, a calorie chart, a goal for the next session and a personalised PDF report. Everything runs in a 3D-printed chassis.

## Features
- Real-time pose detection (MediaPipe Pose + Hands, OpenCV); joint angles from MediaPipe's 3D world landmarks when available, otherwise the 2D image points
- Rep counting per arm. A rep only counts if it starts from a straight arm, the upper arm points down and stays by the side, the wrist stays straight, the lift is neither too fast nor too slow and the arm is not dropped back down too fast. The lift and the lowering are timed from the wrist's height, and a rep counts once the arm is back down
- Weight-in-hand check (CNN): a small neural network (MobileNetV3-Small, fine-tuned on hand pictures from labelled clips) looks at each hand on the front camera and decides "holding a weight" or "empty hand", once per rep. It is advice only: when it happened in 2 or more reps, the phone page shows a "No weight in your hand?" card with pictures. See "Weight-in-hand CNN" below
- One camera in the final build: the Raspberry Pi AI Camera in front. A second USB webcam at the side (`--side-camera 0`) was built and tested but is not used: with its 1 m cable it could not be placed at a good distance for a side view (it missed the left hand), and with the CNN two cameras ran at only 8-10 FPS (28 Oct demo video) against about 15 FPS with one. The option is still in the code
- When a curl is not counted, the screen shows why and what to do (e.g. "Keep your upper arm pointing down"), with a short pause before the next rep
- Spoken feedback (offline Piper voice): the rep count, why a rep was not counted and what to do, live arm warnings during the lift, a greeting after logging in and the session result with calories burned. Only feedback the system is reliable at is spoken - the hand checks are not - and it never repeats itself or talks over itself. See "Spoken feedback" below
- Personalised training report (PDF) for any period: calories burned, reps, form, training days, what to work on and progress, downloaded from the phone page or made for every active account with `tools/make_reports.py`. See "Training report" below
- Curl guide: an animated stick figure showing a correct curl and the key rules (fist facing the body), shown
  once the position check has passed - so the person is standing where they can see it - then "Start curling".
  Curls made during the guide are not counted (`--no-demo` skips it)
- No keyboard needed: the window opens full screen, and a session ends when you walk away (5 s) or stop curling (30 s) - in **Follow my goal**, not during the rest between sets
- Position check before the first rep: head, upper body and both hands in view, facing the camera, a sensible
  distance and roughly in the middle - a checklist on screen and one spoken instruction at a time ("Step back so
  your head is in view"). Curls only count once the position has been good for 1 s; during the session a
  position problem lasting 2 s is shown and said once, but does not stop counting. See "Position check" below
- Steady display: the drawn arm points are smoothed (One-Euro filter; the counting has its own smoothing), and the
  "Hi <name>" / QR screen only appears once nobody has been seen for 2 s, so a moment of lost tracking does not
  flip the screen
- Camera watchdog: if the Pi camera sends no picture for 3 s (seen when the Pi was hot and throttled), it is restarted by itself
- Accounts on the phone app (username + password, email, body weight). Until someone logs in, the device shows a big QR code (also with a person in view - nothing starts before a login anyway): scan it, log in, tap **Train on this device**; the session is saved to your account and the device logs out afterwards. Curls only count after logging in (`REQUIRE_LOGIN` in `fitform/config.py`; not needed with `--no-server` or `--video`)
- "What will you lift?" after **Train on this device**: dumbbells (kg each), water bottles (litres each; water is about 1 kg per litre), something else (kg each) or no weight - pre-filled with the last answer. The weight is saved with the session and shown on the phone page, in the history and in the report, and the advice to add weight uses it: 2-10 %, the lower end for the biceps (ACSM 2009, p. 690), e.g. "from 0.5 kg to about 0.51-0.55 kg". Choosing "no weight" also stops the "No weight in your hand?" card. Calories are not changed by it: they come from MET x 3.5 x body weight / 200 per minute (see "Where the goals come from")
- Forgot password: the phone page emails a 6-digit code (valid 10 minutes, 5 tries, at most one a minute; only its hash is stored). The username must have the exact capitals, as at login; an unknown username or email shows "This username or email is not registered.". The sending account is set up once with `tools/setup_email.py`. Accounts made before emails were asked add one under Settings (needs the password). On the device itself `tools/reset_password.py` still works
- Phone app dashboard: next session goal (sets x reps per arm, kcal, minutes), sessions this week, calories per session against each session's goal, last session, why curls were not counted, history, CSV download
- Goals from published guidelines (see "Where the goals come from")
- Fist direction and grip (hand not clenched) are advisory (see Known limitations, `FIST_REJECTS = False`): the rep still counts, and the app shows a warning with pictures from the camera when it happened in 2 or more reps
- Green/red form status on the touch display and spoken feedback through a Bluetooth speaker. These replaced the green/red LEDs and buzzer planned at the start: the display is already in front of the user, and a voice can say why a curl was not counted, which a beep cannot. `fitform/gpio_feedback.py` is still in the code (nothing is wired to it; `--no-gpio` turns it off)
- Calorie estimate: MET x 3.5 x body weight / 200 per active minute (from the first to the last curl) - the formula printed by the Compendium of Physical Activities
- Session log: CSV (`logs/sessions.csv`) plus a detailed history (`logs/sessions.jsonl`). A session in which no
  rep was counted (only rejected curls: 0 reps, 0 kcal) is not saved and does not count anywhere - history,
  goals, "this week" or reports; the voice says "No reps were counted, so this session was not saved."

## Hardware (final build)
| Part | Details |
|---|---|
| Raspberry Pi 5 (8 GB) | runs everything; Raspberry Pi OS Trixie, 64 GB microSD |
| Raspberry Pi AI Camera (Sony IMX500) | front camera, CSI ribbon cable, mounted upright at the top of the chassis |
| 7-inch touch display | DSI ribbon cable; live view, count, form status, QR code and touch settings (speaker, X to close) |
| Bluetooth speaker | outside the chassis, paired from the touch screen; spoken feedback |
| Official Raspberry Pi 27 W USB-C power supply | 5.1 V, 5 A |
| 3D-printed chassis | designed in Fusion 360, printed in PLA on a Bambu Lab X1 Carbon (main body 13 h 40 min with supports, about 392 g); carry handle, front frame around the display, vents |

Block diagram, photos and the chassis CAD model: [docs/](docs/README.md). Nothing is wired to the GPIO pins.

## Project structure
```
fitform-ai/
├── main.py                  # entry point - runs the whole system
├── VIDEOS.md                # links to the demo videos
├── fitform/
│   ├── config.py            # all settings (cameras, thresholds, GPIO pins, sessions...)
│   ├── camera_detect.py     # finds the cameras: AI Camera front, USB webcam side or front
│   ├── camera_thread.py     # background camera capture (no lag / buffering)
│   ├── pose_engine.py       # MediaPipe Pose wrapper
│   ├── bicep_curl.py        # joint angles + rep-counting state machine
│   ├── hand_check.py        # MediaPipe Hands: fist / grip and fist direction per arm
│   ├── hand_state.py        # fist / grip and direction classification (no camera needed)
│   ├── fist_calib.py        # optional per-arm fist-direction calibration
│   ├── side_palm.py         # side camera: palm direction and grip
│   ├── hold_check.py        # weight-in-hand CNN: cuts the hand picture and runs the model (OpenCV DNN)
│   ├── feedback_engine.py   # runs the rep counters and chooses the feedback text
│   ├── display_ui.py        # on-screen overlay, demo, QR code and 'session saved' screens
│   ├── position.py          # position check before the first rep
│   ├── speaker.py           # Bluetooth speaker: pairing, reconnecting, test sound
│   ├── speaker_ui.py        # speaker settings screens on the touch display
│   ├── gpio_feedback.py     # LEDs + buzzer from the original plan (not wired in the final build)
│   ├── calorie_tracker.py   # MET-based calorie estimate
│   ├── session.py           # ends a session when the user walks away or stops
│   ├── session_summary.py   # end-of-session totals
│   ├── plan.py              # goal for the next session (ACSM / WHO / Compendium)
│   ├── voice.py             # text-to-speech (Piper): one sentence at a time, priorities, no repeats
│   ├── equipment.py         # what the user lifts (asked on the phone) and the advice to add weight
│   ├── mailer.py            # sends password-reset codes by email (SMTP over SSL)
│   ├── coach.py             # decides what is said out loud (reliable feedback only)
│   ├── report.py            # personalised training report (PDF with charts)
│   └── session_logger.py    # accounts, session storage and the phone app (Flask)
├── models/
│   ├── hand_holding.onnx    # trained weight-in-hand CNN (MobileNetV3-Small, ONNX)
│   ├── hand_holding_report.txt   # training data and test results of the CNN
│   └── voices/              # Piper voice (downloaded by tools/setup_voice.py, not uploaded to GitHub)
├── tools/
│   ├── fist_calibrate.py    # builds the fist-direction calibration from labelled runs
│   ├── record_clips.py      # records labelled two-camera test clips (rep checks and CNN training data)
│   ├── hand_crops.py        # cuts labelled hand pictures out of the clips for training
│   ├── eval_hand_classifier.py   # compares hand-classifier models on the same test pictures
│   ├── train_hand_classifier.py  # trains the CNN and writes models/ (PyTorch, runs in ~/cnn_env)
│   ├── imx500_bottle_test.py     # test: can the AI Camera's on-chip object detector see a bottle?
│   ├── setup_voice.py       # downloads the voice, prepares the spoken phrases, tests the speaker
│   ├── setup_email.py       # sets up the email account for password-reset codes (sends a test email)
│   ├── make_reports.py      # PDF report for every account that trained in a period
│   ├── reset_password.py    # sets a new password for an account
│   ├── run_fitform.sh       # desktop launcher (--install adds the FitForm AI icon)
│   ├── fitform.desktop      # desktop / menu entry for the launcher
│   └── fitform_icon.png     # icon for the launcher
├── prototypes/
│   └── bicep_curl_single_camera.py   # original single-file laptop prototype
├── docs/
│   ├── README.md            # list of the project documents
│   ├── gantt/               # Gantt chart (Excel, PDF, picture)
│   ├── figures/             # block diagram, CNN results, two-camera test, chassis CAD model
│   ├── photos/              # photos of the parts and the finished device
│   └── website/             # screenshots of the phone app and an example PDF report
├── tests/
│   ├── test_logic.py        # tests for counting, goals, accounts and the app (no camera needed)
│   ├── test_voice_report.py # tests for the spoken feedback and the training report
│   └── test_speaker.py      # tests for the speaker settings
├── logs/                    # sessions, accounts, hand pictures, clips and training crops (not uploaded to GitHub)
└── requirements.txt
```

## Setup

### Windows laptop (development)
```powershell
python -m venv C:\Users\<you>\fitform_env
C:\Users\<you>\fitform_env\Scripts\activate
pip install -r requirements.txt
```
Keep the virtual environment outside OneDrive. Syncing thousands of package files slows everything down.

### Raspberry Pi 5 (Raspberry Pi OS Trixie, 64-bit)
Trixie ships Python 3.13, but the MediaPipe Pose API used here (`mediapipe==0.10.18`) only has Pi (aarch64) builds for Python 3.11/3.12. So FitForm gets its own Python 3.12 environment, installed with `uv`, next to the system Python.
```bash
sudo apt update && sudo apt install -y libportaudio2 rpicam-apps git
curl -LsSf https://astral.sh/uv/install.sh | sh
source $HOME/.local/bin/env
uv venv --python 3.12 ~/fitform_env
source ~/fitform_env/bin/activate
cd ~/Final-Year-Project-FitForm-AI
uv pip install -r requirements.txt
python tools/setup_voice.py       # once: downloads the voice (63 MB) and prepares the spoken phrases
python tools/setup_email.py       # once: email account for password-reset codes (e.g. Gmail + app password)
```
The AI Camera is read through the `rpicam-vid` command (`--camera picam`), so Picamera2 is not needed inside the environment. A USB webcam uses `--camera 0`.

Check the install:
```bash
python -c "import mediapipe as mp, cv2; mp.solutions.pose.Pose(); print('MediaPipe', mp.__version__, 'OpenCV', cv2.__version__)"
rpicam-hello --list-cameras     # AI Camera detected?
```

## Usage
Run from the project folder (on the Pi, first `source ~/fitform_env/bin/activate`):
```bash
python main.py                    # finds the cameras by itself (see below)
python main.py --no-side          # use one camera even if two are connected
python main.py --camera picam --side-camera 0   # choose the cameras yourself (--rotate 180 if mounted upside down)
python main.py --weight 65        # your body weight in kg for calories
python main.py --video clip.mp4   # test on a recorded video
python main.py --no-demo --no-gpio --no-server --debug
python main.py --windowed         # normal window instead of full screen
python main.py --no-hold          # turn off the weight-in-hand CNN
python main.py --no-voice         # no spoken feedback
python main.py --no-position-check   # count curls without the position check first
```
Cameras are found automatically: the Raspberry Pi AI Camera is the front camera when it is connected and a
USB webcam becomes the side camera; without the AI Camera, the USB webcam is the front camera. At least one
camera is needed. The AI Camera is mounted upright (since 18 Nov 2026; it was upside down before, so the
recordings from October are turned 180 degrees) - change `PICAM_ROTATE` / `WEBCAM_ROTATE` in
`fitform/config.py` if your mounting differs.

With nobody in front of it, the device shows a QR code with its address (e.g. `http://192.168.1.23:5000`).
Scan it with a phone on the same Wi-Fi, log in or create an account, and tap **Train on this device**.
Then choose how to train:
- **Follow my goal** (e.g. 3 sets x 8 per arm): the screen shows "Set 1 of 3  Left 5/8  Right 6/8". When both arms
  have done the set, FitForm says "Set 1 done. Rest 60 seconds." and counts the rest down (ACSM 2009: 1-2 min for
  exercises like curls). You may step out of view while resting; a curl ends the rest early. After the last set the
  session is saved. Only these sessions move your goal up.
- **Challenge yourself**: as many good curls as you can; saved 30 s after your last curl. It does not change your
  goal, but can set a new personal best.

Either way a session also ends when you walk out of view for 5 s or stop curling for 30 s (never during a rest);
the screen then shows the totals and your next goal, and everything is on the phone app.
On the touch screen, tap the **X** in the top-right corner twice to close FitForm (a running session is saved).

Speaker for the spoken feedback: tap **Speaker** (top right, between sessions). Any Bluetooth speaker works -
**Find new speaker**, put the speaker in pairing mode, tap its name; a PIN keypad appears only if the speaker asks
for one (usually 0000). Already paired speakers and other outputs (e.g. HDMI) are listed to switch between, or
**No speaker (text only)** mutes the voice. **Test sound** checks it. The choice is kept in `logs/speaker.json` and
the speaker is reconnected when FitForm starts (`fitform/speaker.py`, screens in `fitform/speaker_ui.py`).
(With a keyboard: **Q** quits and saves, **R** resets.)

Desktop icon: `bash tools/run_fitform.sh --install` puts a **FitForm AI** icon on the Pi's desktop and in the menu
(Education). Tapping it starts FitForm full screen; it never starts a second copy, and the output goes to
`logs/fitform_app.log`. The first time, the file manager asks what to do - choose **Execute**.

Optional: `tools/fist_calibrate.py` builds a per-arm calibration of the fist-direction reading from labelled
`--debug` runs (instructions at the top of the file). Thresholds are in `fitform/config.py`.

### Camera set-up
- Stand about **2-3 m** from the front camera so your **head**, whole upper body, elbows and both hands stay in
  view. MediaPipe Pose finds a person far more reliably with the head in the picture: in a recording with the head
  cut off (15 Nov) it found the person in 40 % of pictures, against 69 % with the face visible; when it loses you,
  the arm drawing jumps and the counting pauses.
- Keep the chassis vents clear. The final build has no fan and normally runs at about 15 FPS, but during one
  long session on 15 Nov the Pi reached 95 C, slowed its CPU to 1.0 GHz and FitForm dropped to 7-9 FPS; for long
  sessions a fan (e.g. the Raspberry Pi 5 Active Cooler) helps.
- Optional side webcam (not used in the final build): level with your hip, as close to 90 degrees from the front
  as the cable allows.
- Good, even lighting; avoid a bright window behind you.

Other addresses: `http://<pi-ip>:5000/sessions` (JSON), `http://<pi-ip>:5000/sessions.csv` (download).

## Weight-in-hand CNN
FitForm checks whether there is actually a weight in the hand with a small image classifier: MobileNetV3-Small
(pretrained on ImageNet, last layer replaced by 2 outputs "empty" / "holding", all layers fine-tuned) on a
128x128 picture cut around each hand, just past the wrist along the forearm.

How it was made (data and all results in `models/hand_holding_report.txt`):
1. `tools/record_clips.py hands <round>` (water bottle) or `dumbbells <round>` (dumbbells in both / the right /
   the left hand) records labelled clips, plus empty fist and open hand. It uses the AI Camera when connected,
   otherwise the USB webcam.
2. `tools/hand_crops.py` uses MediaPipe Pose to find each wrist and saves the hand picture, labelled from the
   clip name (rounds 1-2, bottle, 27 Oct: 9556 pictures; rounds 3-4, 0.5 kg dumbbells, 15 Nov: 8695 pictures).
3. `tools/train_hand_classifier.py` trains the model with PyTorch; `--out` puts a candidate in another folder.
4. `tools/eval_hand_classifier.py` scores models on the same test pictures through OpenCV, as the app runs them;
   a new model only replaces `models/hand_holding.onnx` if it is better.

Results: the first model (bottle only) recognised a dumbbell in only **7 %** of pictures, so nearly every
dumbbell rep was reported as "no weight" (live test 15 Nov). The model in use is trained on rounds 1-3 and
tested on round 4, a separate recording it never saw: **98.1 %** of 2900 pictures, dumbbell **96.9 %**, empty
hands 93.5-100 %; per rep, as the app decides, **97.9 %** of holding reps and **99.1 %** of empty-hand reps are
right. On the bottle it is unchanged (99.9 %), and it is just as fast (6.5 ms vs 6.4 ms per hand).

In FitForm the model runs through OpenCV's DNN module (about 5 ms per hand), so `fitform_env` does not need
PyTorch. The hands are classified every 3rd frame and each rep gets one vote: with at least 3 readings and
60 % or more of them "empty", the rep is marked "no weight". This is advice only (`HOLD_REJECTS = False` in
`fitform/config.py`): the rep still counts. `--no-hold` turns the check off.

Training needs PyTorch, which is kept in its own environment so the app's environment stays small:
```bash
python3 -m venv ~/cnn_env
~/cnn_env/bin/pip install torch torchvision pillow numpy onnx
~/cnn_env/bin/python tools/train_hand_classifier.py --train 1 --test 2
```

## Position check
Before the first rep of a session, FitForm checks that the person stands where the camera can judge their
curls, using only the pose landmarks (`fitform/position.py`, limits in `fitform/config.py`, `POSITION_*`):

| Check | Measured as | Instruction when it fails |
|---|---|---|
| Upper body in view | both hips seen, shoulders not too wide | "Step back so your whole upper body is in view" |
| Head in view | nose and eyes seen, at a body-like height above the shoulders | "Step back so your head is in view" |
| Both hands in view | elbows and wrists seen, wrists inside the picture | "Keep both hands in view, arms down by your sides" |
| Facing the camera | shoulder width / torso length | "Turn to face the camera" |
| Distance | shoulder width as a share of the picture | "Come a little closer" |
| In the middle | middle of the shoulders | "Move a little to your left / right" |

The screen shows the checklist and the first instruction; each instruction is spoken once (said again only after
nobody has been seen for 10 s - standing too close, the pose model can lose a person for a few seconds). When
everything has been good for 1 s: "Good position. Here is how to do a bicep curl." - the curl guide plays
(8 s), then "Start curling". Curls before that are not counted. During the session a
problem that lasts 2 s is shown and said once, but counting goes on.

The limits come from measurements (15 Nov): 5 recorded clips with good framing (1847 pictures) against a
screen recording where the user stood too close with the head cut off - for example the shoulder width was
0.19-0.22 of the picture in good framing and 0.31-0.51 too close, and the hips were seen in good framing but not
when too close. On 8 good clips the check passed after exactly 1.0 s and the counted reps did not change
(slow-curl clip: 11 with and without it); on the bad recordings it never passed. With the head cut off, the pose
model sometimes invents a face, so "Head in view" alone can be fooled; the other checks and the 1 s hold catch it.

## Spoken feedback
In the final build FitForm speaks through a Bluetooth speaker placed outside the chassis and paired from the touch
screen (the DSI touch display has no speakers and the Pi 5 has no headphone socket). A USB speaker or an HDMI
monitor with speakers also works. The voice is [Piper](https://github.com/rhasspy/piper),
a neural text-to-speech model that runs offline on the Pi's CPU (`en_GB-cori-medium` by default,
`VOICE_MODEL` in `fitform/config.py`). Set it up once with `python tools/setup_voice.py`; it downloads the voice,
prepares the fixed phrases (about 20 s) and plays a test sentence.

What is said - only feedback the system is reliable at:

| When | Example |
|---|---|
| After logging in on the phone | "Hi Steve. Let's check your position." |
| Position check (each instruction once) | "Step back so your head is in view." ... "Good position. Start curling." |
| A rep is counted | "5" (or "Right, 5" while both arms are in use) |
| A rep is not counted for an arm or tempo reason | "Not counted. Keep your elbow by your side." |
| During the lift, an arm fault lasting 0.4 s | "Keep your upper arm pointing down" |
| The session is saved | "Session saved. 24 reps counted. About 6 calories burned. Goal reached! Next goal: 3 sets of 10 per arm." |

The hand checks (grip, fist direction, weight in the hand, hand not visible) are never spoken: they can be wrong
(see Known limitations), so they stay on the phone page, with pictures. A rep rejected only for a hand reason
just says "Not counted."

No repeats, no clashes: one sentence at a time, never cut off; a more important sentence replaces a less
important one that is still waiting; a rep number or tip that cannot be said in time is dropped rather than said
late; the same fix is said at most once in 20 s (after that just "Not counted."); a live warning that was just
said is not repeated by the rejection that follows; both arms finishing together become one sentence. Every
sentence is also printed in the terminal as `[VOICE] "..."`. Settings: `VOICE_*` in `fitform/config.py`;
`--no-voice` turns it off. Without a speaker, Piper or the voice file, FitForm runs silently as before.

Speech uses one CPU core at low priority, and phrases are made once and kept in `~/.cache/fitform/voice`, so the
frame rate is unchanged (tested 15 Nov: 14.3-14.6 FPS with the voice, 14.3 without, on a recorded clip).

## Training report
A personalised PDF report for one account over any period: sessions and training days, reps (right / left),
share of curls counted, **calories burned** (total, per session against each session's goal, best session),
active time, average lift time, charts per session, training days per week against the WHO target, the main
reasons curls were not counted with what to do, goal progress, a comparison with the previous period of the same
length, and every session in a table.

- **On the phone:** the dashboard's **My report (PDF)** card - choose the dates, or last 7 / 30 days / all.
- **On the device, for every account that trained in a period:**
  ```bash
  python tools/make_reports.py                 # last 7 days
  python tools/make_reports.py --days 30       # last 30 days
  python tools/make_reports.py --from 2026-11-01 --to 2026-11-30 --user Steve
  ```
  The PDFs go to `logs/reports/` (not uploaded to GitHub - they hold personal data).

The phone page makes the report in a separate Python process at low priority (about 3 s on the Pi 5), so the
camera loop keeps its speed. Made inside the app's own process it held Python's interpreter lock for about a
second and the frame rate dipped to about 9-10 FPS (15 Nov); in its own process the lowest reading was 11.4 FPS,
within the clip's normal 12-18 FPS range. `tools/make_reports.py` also runs on a laptop with a copy of `logs/`.

## Where the goals come from
Each rule was checked against the source's own text (16 Nov 2026); the quotes below are verbatim.

| FitForm uses | Source says | Where |
|---|---|---|
| 3 sets per arm | "one to three sets per exercise be used by novice individuals initially" | ACSM 2009, p. 691 |
| | "healthy adults are advised to complete at least two sets per exercise" | ACSM 2026 update |
| 8 -> 10 -> 12 reps | "8–12 repetitions per set for one to three sets per exercise" (novice and intermediate) | ACSM 2009, p. 694 |
| 1 min rest between sets | "For assistance exercises (those exercises complimentary to core exercises), a shorter rest period length of 1–2 min may suffice" | ACSM 2009, p. 692 |
| Add 2-10 % weight (lower end for the biceps) | "2–10% (lower percent for small muscle mass exercises, higher percent increase for large muscle mass exercises) increase in load be applied when the individual can perform the current workload for one to two repetitions over the desired number on two consecutive training sessions" | ACSM 2009, p. 690 |
| At least 2 training days a week | "muscle-strengthening activities at moderate or greater intensity that involve all major muscle groups on 2 or more days a week" | WHO 2020, Table 4 |
| 3.5 MET | code 02054, 3.5 MET: "Resistance (weight) training, multiple exercises, 8-15 reps at varied resistance" | Compendium 2024 |
| kcal per minute = MET x 3.5 x body weight (kg) / 200 | "METS to Kcal/min = multiply METS x 3.5 x body weight in kg then divide by 200" | Compendium website, Unit Conversions |

Notes, so nothing is claimed that the sources do not say:
- The step up the ladder (3x8 -> 3x10 -> 3x12, a step when the goal is reached with at least 50 % of curls
  counted; a weight increase after 3x12 on two sessions in a row) is FitForm's adaptation of the 2009 rule.
- The kcal formula is printed on the Compendium's website, not in the paper; the paper (section 2.5) says
  "Additional equations used to convert EE values are available on the Compendium website". The paper
  itself notes the values do "not reflect precise individual EE values", so calories are an estimate.
- The 2026 ACSM update also says "progression is not necessary to achieve beneficial outcomes": the ladder is
  for people who want to keep progressing.
- The kcal goal is the estimate for doing the session's goal at about 3 s per rep with 60 s rests.

Sources:
- American College of Sports Medicine (2009). Position stand: Progression models in resistance training for
  healthy adults. *Med Sci Sports Exerc* 41(3):687-708. doi:10.1249/MSS.0b013e3181915670
- Currier BS, et al. (2026). ACSM position stand: Resistance training prescription for muscle function,
  hypertrophy, and physical performance in healthy adults: an overview of reviews. *Med Sci Sports Exerc*
  58(4):851-872. doi:10.1249/MSS.0000000000003897
- Bull FC, et al. (2020). World Health Organization 2020 guidelines on physical activity and sedentary
  behaviour. *Br J Sports Med* 54(24):1451-1462. doi:10.1136/bjsports-2020-102955
- Herrmann SD, et al. (2024). 2024 Adult Compendium of Physical Activities: a third update of the energy costs
  of human activities. *J Sport Health Sci* 13(1):6-12. doi:10.1016/j.jshs.2023.10.010
- Compendium of Physical Activities. Unit Conversions. https://pacompendium.com/unite-conversions/ (accessed
  19 Nov 2026) - the website of the 2024 Adult Compendium

## Known limitations
- **Fist direction (turned outward vs. facing the body)** cannot be detected reliably. Tested with one camera,
  two cameras and a per-arm calibration from labelled runs (21 Oct 2026): the reading separates the two cases
  within one session, but the same correct curl can read anywhere from "correct" to "turned out" between reps
  and sessions (it depends on small wrist rotations and on camera placement). It is therefore advisory only.
- **Clenched fist vs. open hand** is judged from the hand landmarks, which flicker frame to frame, and a hand
  round a bottle or dumbbell can look open. It is therefore advisory as well.
- **Weight in the hand (CNN)** is trained on one person, one plastic bottle, one pair of 0.5 kg dumbbells and
  two rooms. Mistakes seen: motion-blurred open hands, a yellow pole in the background read as the (yellow)
  bottle, and an empty hand next to a hand holding a dumbbell (93.5 % right). It is therefore advisory only.
  Next step: other people, other weights and rooms.
- Accounts are stored on each device; several devices sharing one account list would need a central server.
- **Correct curls are counted reliably; wrong ones less so** - the arm checks (upper arm, elbow, tempo,
  extension) catch bad reps well, the hand checks less consistently.
- Calories are an estimate (MET formula), not a measurement. The plan is general guidance, not coaching.
- Frame rate on the Pi 5 is about 15 FPS with one camera (8-10 FPS with two cameras and the CNN), so very fast
  reps can be timed less accurately.
- **Testing:** the author's own sessions were screen-recorded and checked; the supervisor and a volunteer also
  tried the prototype, but their sessions were not recorded, so there is no exact accuracy figure for other people.
- **Spoken rep numbers can be skipped** when both arms finish reps in quick succession: a number that cannot
  be said before the next rep is dropped rather than said late (by design - no clashes, no out-of-date counts).
  The screen always shows the count.

## Wiring
Nothing is wired to the GPIO pins in the final build: the AI Camera (CSI ribbon) and the touch display (DSI ribbon)
plug into the Pi, and the speaker connects by Bluetooth. The LEDs and buzzer from the original plan can still be
connected (default BCM pins below, change in `fitform/config.py`):

| Component | GPIO pin | Notes |
|---|---|---|
| Green LED | GPIO 17 | via 220-330 Ω resistor to GND |
| Red LED | GPIO 27 | via 220-330 Ω resistor to GND |
| Buzzer (active, 5V/3.3V) | GPIO 22 | other leg to GND |

## Tests
126 tests, no camera needed:
```bash
python tests/test_logic.py         # 72: counting, goals, accounts, the app
python tests/test_voice_report.py  # 45: spoken feedback and the training report
python tests/test_speaker.py       # 9: speaker settings
```

## Tested versions
Raspberry Pi 5: mediapipe 0.10.18, Python 3.12, opencv-python 4.11.0.86, numpy 1.26.
Laptop: mediapipe 0.10.21, Python 3.10-3.12 (both pinned in `requirements.txt`).
MediaPipe 1.0+ removed the `mp.solutions.pose` API this project uses, so keep the version pinned.

## Privacy
Video is processed in memory and not recorded. Exercise numbers are logged on the Pi; passwords and
password-reset codes are stored hashed (PBKDF2) in `logs/users.json`, together with each account's email
(used only for reset codes). The account FitForm sends email from, with its app password, is in
`logs/mail.json` (readable by the device's owner only). Like everything in `logs/`, none of this is uploaded to
GitHub. The phone page uses plain HTTP on the local Wi-Fi, so passwords and codes travel unencrypted within that
network. When a rep looked like it was
done with the fist turned out, the hand not gripping or no weight in the hand, a small picture of the hand is saved
in `logs/snaps/` (at most 6 per session) so you can check it on the phone page; it is only reachable on the local Wi-Fi. Set `MAX_SNAPSHOTS = 0` in
`fitform/config.py` to turn this off, and delete `logs/` to remove all data.
