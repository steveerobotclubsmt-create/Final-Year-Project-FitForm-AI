"""FitForm AI - entry point.

Examples:
  python main.py                      # finds the cameras: Pi camera in front, USB webcam at the side
  python main.py --no-side            # one camera only
  python main.py --camera picam --rotate 180 --side-camera 0   # choose the cameras yourself
  python main.py --camera 1           # a particular webcam as the only camera
  python main.py --video test.mp4     # run on a recorded video instead of a camera
  python main.py --debug              # print live angles and hand readings
"""

import argparse
import os
import time

import cv2

from fitform import config
from fitform.calorie_tracker import CalorieTracker
from fitform.camera_thread import CameraStream
from fitform.coach import Coach
from fitform.display_ui import ArmSmoother, draw_arm, draw_banner, draw_debug, draw_demo, draw_hud, draw_idle, \
    draw_position, draw_qr_corner, draw_saved, fit_to_screen
from fitform.feedback_engine import FeedbackEngine
from fitform.gpio_feedback import GPIOFeedback
from fitform.hand_check import HandChecker
from fitform.pose_engine import PoseEngine
from fitform.equipment import label as eq_label
from fitform.plan import make_plan
from fitform.position import ADVICE, DriftWatch, PositionGate, check_position
from fitform.session import SessionTracker, curls_allowed, nobody_there
from fitform.session_logger import SessionLogger, local_ip, start_server
from fitform.session_summary import build_summary, counts_as_session, print_summary
from fitform.voice import Voice


def parse_args():
    p = argparse.ArgumentParser(description="FitForm AI - bicep curl trainer")
    p.add_argument("--camera", default="auto",
                   help="'auto' (default: Pi camera in front if present, a USB webcam as side or front), "
                        "'picam', or a webcam index (0, 1, ...)")
    p.add_argument("--no-side", action="store_true", help="use one camera only, even if two are found")
    p.add_argument("--video", help="video file to use instead of a camera")
    p.add_argument("--weight", type=float, default=config.USER_WEIGHT_KG, help="body weight in kg")
    p.add_argument("--no-gpio", action="store_true", help="disable LEDs/buzzer")
    p.add_argument("--no-server", action="store_true", help="disable the Flask web server")
    p.add_argument("--headless", action="store_true", help="no window (for testing)")
    p.add_argument("--windowed", action="store_true", help="normal window instead of full screen")
    p.add_argument("--no-fist", action="store_true", help="do not require a clenched fist")
    p.add_argument("--no-palm", action="store_true", help="turn off the palm-direction check")
    p.add_argument("--no-hold", action="store_true", help="turn off the 'weight in the hand' check (CNN)")
    p.add_argument("--no-voice", action="store_true", help="turn off the spoken feedback")
    p.add_argument("--no-position-check", action="store_true",
                   help="count curls without checking the position first")
    p.add_argument("--debug", action="store_true", help="print live angles and hand readings in the terminal for tuning")
    p.add_argument("--debug-screen", action="store_true", help="also show the tuning numbers on the video window")
    p.add_argument("--angles", choices=["3d", "2d"], help="elbow angle from 3D world landmarks or 2D image points")
    p.add_argument("--rotate", type=int, choices=[0, 90, 180, 270], default=None,
                   help="rotate the front camera picture (default: PICAM_ROTATE for the Pi camera, "
                        "WEBCAM_ROTATE for a webcam, see config.py)")
    p.add_argument("--no-demo", action="store_true", help="skip the start-up demo animation")
    p.add_argument("--side-camera", help="second camera at your side (e.g. 0 for the USB webcam) that judges the palm")
    p.add_argument("--side-arm", choices=["right", "left"], default="right",
                   help="which arm the side camera is next to (default right)")
    p.add_argument("--side-rotate", type=int, choices=[0, 90, 180, 270], default=None,
                   help="rotate the side camera picture (default: WEBCAM_ROTATE)")
    return p.parse_args()


def main():
    args = parse_args()
    W, H = config.DISPLAY_WIDTH, config.DISPLAY_HEIGHT

    auto_side = None
    if args.video:
        source = args.video
    elif args.camera.lower() == "auto":
        from fitform.camera_detect import detect
        source, auto_side = detect()
        if source is None:
            print("ERROR: no camera found. Connect the Raspberry Pi AI Camera or a USB webcam "
                  "(check with: rpicam-hello --list-cameras  and  ls /dev/video*)")
            return
        if args.no_side:
            auto_side = None
    elif args.camera.lower() == "picam":
        source = "picam"
    elif args.camera.lower() == "usb":
        source = config.CAMERA_INDEX
    else:
        source = int(args.camera)
    if args.side_camera is None and auto_side is not None:
        args.side_camera = str(auto_side)
    if args.rotate is None:                     # each camera type keeps its own mounting rotation
        args.rotate = config.PICAM_ROTATE if source == "picam" else (0 if args.video else config.WEBCAM_ROTATE)
    if args.side_rotate is None:
        args.side_rotate = config.PICAM_ROTATE if args.side_camera == "picam" else config.WEBCAM_ROTATE
    stream = CameraStream(source, config.CAPTURE_WIDTH, config.CAPTURE_HEIGHT)
    if not stream.is_opened():
        print(f"ERROR: could not open {source!r}. Try another camera with --camera 1 "
              "(or --camera picam for the Pi Camera Module; check it with: rpicam-hello --list-cameras)")
        return
    stream.start()
    print(f"Front camera: {source!r} (rotate {args.rotate})")

    engine = PoseEngine()
    feedback = FeedbackEngine()
    if args.no_fist:
        config.FIST_CHECK = False
    if args.no_palm:
        config.PALM_CHECK = False
    if args.no_position_check:
        config.POSITION_CHECK = False
    if args.angles:
        config.USE_3D_ANGLES = args.angles == "3d"
    print(f"Angles: {'3D' if config.USE_3D_ANGLES else '2D'} | straight above {config.DOWN_ANGLE} | "
          f"curled below {config.UP_ANGLE} | palm check {'on' if config.PALM_CHECK else 'off'} | "
          f"fist check {'on' if config.FIST_CHECK else 'off'} | lift {config.MIN_UP_SECONDS}-{config.MAX_UP_SECONDS} s")
    hands = HandChecker() if (config.FIST_CHECK or config.PALM_CHECK) else None
    holder = None
    if config.HOLD_CHECK and not args.no_hold:
        try:
            from fitform.hold_check import HoldClassifier
            holder = HoldClassifier()
            print(f"Weight check: {config.HOLD_MODEL} every {config.HOLD_EVERY_N} frames "
                  f"({'rejects' if config.HOLD_REJECTS else 'advice only'})")
        except Exception as e:                  # model file missing / unreadable: run without it
            print(f"Weight check off: could not load {config.HOLD_MODEL} ({e})")
    calories = CalorieTracker(weight_kg=args.weight)
    gpio = GPIOFeedback(enabled=not args.no_gpio and config.GPIO_ENABLED)
    logger = SessionLogger()
    if config.FLASK_ENABLED and not args.no_server:
        start_server(logger)
    voice = Voice(enabled=config.VOICE_ENABLED and not args.no_voice)
    coach = Coach(voice)
    if voice.ready:
        voice.prepare(coach.phrases())
        print(f"Voice: {os.path.basename(config.VOICE_MODEL)} (rep count {'on' if config.VOICE_COUNT_REPS else 'off'}, "
              f"live warnings {'on' if config.VOICE_LIVE_WARNINGS else 'off'})")

    side = None
    if args.side_camera is not None and config.PALM_CHECK:
        from fitform.side_palm import SidePalmChecker
        sc = args.side_camera
        ssrc = "picam" if sc.lower() == "picam" else (int(sc) if sc.isdigit() else sc)   # a file path works for testing
        sstream = CameraStream(ssrc, config.CAPTURE_WIDTH, config.CAPTURE_HEIGHT)
        if not sstream.is_opened():
            print(f"ERROR: could not open the side camera {ssrc!r}")
            return
        sstream.start()
        side = SidePalmChecker(sstream, args.side_arm, args.side_rotate)
        print(f"Side camera {ssrc!r}: judges the {args.side_arm} palm")

    pool = None
    if hands and config.PARALLEL_HANDS:
        from concurrent.futures import ThreadPoolExecutor
        pool = ThreadPoolExecutor(max_workers=2 if side else 1)
    prev_landmarks = None
    cam_w = int(stream.cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    cam_h = int(stream.cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    print(f"Camera {cam_w}x{cam_h}, processing {W}x{H}, pose model {config.MODEL_COMPLEXITY}, "
          f"hands every {config.HAND_EVERY_N} frame(s){' in parallel' if pool else ''}")
    print("Starting... a session ends when you walk away (or stop curling for a while)")
    last_id = -1
    rotate_code = {90: cv2.ROTATE_90_CLOCKWISE, 180: cv2.ROTATE_180,
                   270: cv2.ROTATE_90_COUNTERCLOCKWISE}.get(args.rotate)
    last_dbg = 0.0
    fps, fps_t, fps_n = 0.0, time.time(), 0
    start_t = time.time()
    demo_allowed = not args.no_demo and not args.headless and config.DEMO_SECONDS > 0
    # the curl guide (demo) is shown once the position check has passed - the person is then standing where they
    # can see it and be seen; without the position check it is shown at start-up and for each next person
    demo_on = demo_allowed and not config.POSITION_CHECK
    demo_pending = False
    go_until = 0.0                              # 'Good position - start curling' banner shown until this time
    tracker = SessionTracker()
    snaps, session_tag = [], None
    saved_until, saved_summary, saved_plan = 0.0, None, None
    last_present = None                         # last time someone was seen (for the 'nobody there' screen)
    arm_smoother = ArmSmoother() if config.DRAW_SMOOTH else None
    gate = PositionGate() if config.POSITION_CHECK else None
    drift = DriftWatch()
    pos, drift_key = None, None
    url = f"http://{local_ip()}:{config.FLASK_PORT}" if (config.FLASK_ENABLED and not args.no_server) else logger.dir
    print(f"Phone page: {url}")
    login_required = config.REQUIRE_LOGIN and url.startswith("http") and not args.video
    if login_required:
        print("Log in on the phone and tap 'Train on this device' - curls are not counted before that")

    session_user = None
    session_equipment = None                    # what the user said they lift (asked on the phone)
    qr = None
    try:
        qr = cv2.QRCodeEncoder.create().encode(url) if url.startswith("http") else None
    except (AttributeError, cv2.error):
        qr = None

    def end_session(end_time):
        """Session over: summary + goal for next time, saved to the user's account; device logs out.
        Returns (summary, plan), or (None, None) when no rep was counted - that is not saved as a session."""
        summary = build_summary(feedback, calories, end_time, snapshots=snaps, user=session_user,
                                equipment=session_equipment)
        if counts_as_session(summary):
            plan = make_plan(summary, logger.history(session_user or "guest"), calories.weight_kg)
            print_summary(summary, plan)
            logger.save(summary, plan)
            coach.on_session_end(summary, plan)
        else:
            summary = plan = None
            print(f"[SESSION] no rep was counted ({sum(c.attempted for c in feedback.counters.values())} curls, "
                  "none counted) - not saved as a session")
            for name in snaps:                       # its hand pictures belong to no saved session
                try:
                    os.remove(os.path.join(logger.snap_dir, name))
                except OSError:
                    pass
            coach.on_session_empty()
        logger.clear_device_user()
        coach.on_logout()
        if gate:
            gate.reset()
            drift.reset()
        feedback.reset()
        calories.reset()
        tracker.end()
        return summary, plan

    def save_snapshot(arm, frame, pts, kind):
        """Picture of the hand (front camera, plus the side camera) for the turned-out-fist warning."""
        if len(snaps) >= config.MAX_SNAPSHOTS or pts is None:
            return
        # pts are mirrored screen coordinates but `frame` is the un-mirrored camera picture: mirror x back,
        # or the picture shows the OTHER hand (27 Oct: 'no weight' cards showed the hand holding the bottle)
        x, y = frame.shape[1] - int(pts["wrist"][0]), int(pts["wrist"][1])
        r = 120
        crop = frame[max(0, y - r):y + r, max(0, x - r):x + r]
        if crop.size == 0:
            return
        crop = cv2.resize(cv2.flip(crop, 1), (240, 240))     # mirrored, like the screen
        if side is not None and arm == args.side_arm and side.frame is not None:
            sf = side.frame
            crop = cv2.hconcat([crop, cv2.resize(sf, (int(240 * sf.shape[1] / sf.shape[0]), 240))])
        os.makedirs(logger.snap_dir, exist_ok=True)
        # the arm's curl number (every finished curl, counted or not), shown on the phone page as '3rd curl'
        name = f"{session_tag}_{arm}_{kind}_c{feedback.counters[arm].attempted}.jpg"
        cv2.imwrite(os.path.join(logger.snap_dir, name), crop)
        snaps.append(name)

    window = "FitForm AI - Bicep Curl"
    # full screen on the device (no keyboard to maximise it); switched on after the first picture is shown -
    # before that, the Qt window goes full screen but leaves the picture at 800x600 in the middle (27 Oct)
    fullscreen_pending = config.FULLSCREEN and not args.windowed and not args.headless
    screen, fs_frames = None, 0                 # full-screen size, measured a few frames after switching
    if not args.headless:
        cv2.namedWindow(window, cv2.WINDOW_NORMAL | cv2.WINDOW_KEEPRATIO)   # picture scales, keeps its shape

    try:
        while not stream.finished:
            frame_id, frame = stream.read()
            if frame is None or frame_id == last_id:
                time.sleep(0.002)
                continue
            last_id = frame_id

            now = time.time()
            if rotate_code is not None:
                frame = cv2.rotate(frame, rotate_code)   # camera mounted upside down / sideways
            if frame.shape[1] != W or frame.shape[0] != H:
                frame = cv2.resize(frame, (W, H))
            side_job = pool.submit(side.process) if (side and pool) else None
            if hands and pool:
                # hands run on a second core at the same time as pose; they are matched to the arms
                # using the pose from the previous frame (the arm hardly moves in 1/15 s)
                hand_job = pool.submit(hands.process, frame, prev_landmarks)
                landmarks = engine.process(frame)  # detect on the un-mirrored frame
                hand_states = hand_job.result()
            else:
                landmarks = engine.process(frame)
                hand_states = hands.process(frame, landmarks) if hands else None
            palms = dict(hands.palms) if hands else None
            holds = holder.process(frame, landmarks) if holder else None
            if side:
                if side_job:
                    side_job.result()
                else:
                    side.process()
                if side.state is not None and hand_states is not None:
                    # fist: clenched if EITHER camera sees a fist - a fist one camera sees badly (small, at an
                    # angle) must not fail the rep; an open hand is still caught when neither sees a fist
                    hand_states = dict(hand_states)
                    front_state = hand_states.get(args.side_arm)
                    if side.state == "fist" or front_state == "fist":
                        hand_states[args.side_arm] = "fist"
                    elif front_state is None:
                        hand_states[args.side_arm] = side.state
                # palm: the front camera judges it as usual (straight arm); the side camera's reading is
                # passed separately and only rejects a rep when it is very clear (SIDE_PALM_MIN / SIDE_BAD_*)
            prev_landmarks = landmarks
            image = cv2.flip(frame, 1)             # show mirrored, like a mirror
            events, drawn = feedback.update(landmarks, W, H, now, world=engine.world, hands=hand_states,
                                            hand_points=hands.points if hands else None,
                                            palms=palms,
                                            side_palms={args.side_arm: side.label} if side else None,
                                            holds=holds)
            logged_in = curls_allowed(login_required, session_tag is not None, logger.device_user())
            # position check: before the first rep the person must stand where the camera can judge their curls
            pos = check_position(landmarks.landmark) if (gate and landmarks is not None) else None
            drift_key = None
            if gate and session_tag is None and logged_in and not demo_on:
                if gate.update(pos, now):
                    if demo_allowed:                        # position good: now show how to do a curl
                        print("[POSITION] good - showing the curl guide")
                        demo_on, start_t = True, now
                        coach.on_position_ok(guide=True)
                    else:
                        print("[POSITION] good - curls count from now")
                        go_until = now + 3.0
                        coach.on_position_ok()
                elif pos is not None and pos["problem"]:
                    coach.on_position(pos["problem"], pos["advice"])
            elif gate and session_tag is not None:
                drift_key = drift.update(pos, now)          # during a session: warn only, keep counting
                if drift_key:
                    coach.on_position_drift(drift_key, ADVICE[drift_key])
            positioned = gate is None or gate.passed or session_tag is not None
            # not logged in, not in position yet, or the curl guide is showing: curls are not counted or saved
            if events and (demo_on or not (logged_in and positioned)):
                feedback.reset()
                calories.reset()
                events = []
            if args.debug and now - last_dbg >= 0.5:
                last_dbg = now
                print(f"FPS {fps:.1f}")
                for arm in drawn:
                    c = feedback.counters[arm]; d = c.last
                    if not d:                # counter was just reset (curl before login / position check): nothing yet
                        continue
                    fmt = lambda v: "-" if v is None else f"{v:.0f}"
                    ps = hands.palm_scores.get(arm) if hands else None
                    lr = d.get('len_ratio')
                    print(f"[{arm[0].upper()}] elbow {fmt(d['elbow_angle'])} (2D {fmt(d.get('elbow2d'))} / "
                          f"3D {fmt(d.get('elbow3d'))}) drift {fmt(d['drift'])} tilt {fmt(d.get('tilt'))} "
                          f"len {'-' if lr is None else f'{lr:.2f}'} wrist {fmt(d['wrist_angle'])} "
                          f"hand {d['hand'] or '-'}{'' if not hands or hands.curls.get(arm) is None else f' ({hands.curls[arm]}/4 fingers)'} palm {d.get('palm') or '-'}"
                          f"{'' if ps is None else f' (front {ps[0]:+.2f} inward {ps[1]:+.2f})'}"
                          f"{'' if not holder or holder.probs.get(arm) is None else f' weight {holder.probs[arm]:.2f}'}"
                          f"{f' side {side.label or chr(45)} ({side.score:+.2f})' if (side and arm == args.side_arm and side.score is not None) else ''}"
                          f"{' FORESHORTENED' if d.get('foreshortened') else ''} stage {c.stage or '-'} ready {c.ready}")
            for arm, event in events:
                cnt = feedback.counters[arm]
                ut = cnt.last_up_time
                dt = cnt.last_down_time
                lift = f" (lift {ut:.2f} s" + (f", lower {dt:.2f} s" if dt is not None else "") + \
                    (f", {cnt.last_hand_summary}" if cnt.last_hand_summary else "") + ")" if ut is not None else ""
                if event == "counted":
                    calories.on_rep(now)
                    gpio.beep()
                    tip = " [tip: palm looked turned out]" if feedback.counters[arm].palm_tip else ""
                    print(f"+ {arm.capitalize()} rep {feedback.counters[arm].count} counted{lift}{tip}")
                    if feedback.counters[arm].outward_alert:
                        print(f"! {arm.capitalize()}: fist turned outward in {config.OUTWARD_STREAK} of the last {config.OUTWARD_WINDOW} reps - paused")
                else:
                    why = ", ".join(feedback.counters[arm].last_reasons) or "bad form"
                    print(f"x {arm.capitalize()} rep NOT counted - {why}{lift}")
                if feedback.counters[arm].outward_alert and event != "counted":
                    print(f"! {arm.capitalize()}: fist turned outward in {config.OUTWARD_STREAK} of the last {config.OUTWARD_WINDOW} reps - paused")
            gpio.show_form(feedback.overall_form_ok())
            if events and session_tag is None:              # first curl of a new session
                session_tag = time.strftime("%Y%m%d_%H%M%S")
                session_user = logger.device_user()          # who tapped 'Train on this device' (or guest)
                session_equipment = logger.device_equipment()
                calories.weight_kg = logger.user_weight(session_user) if session_user else args.weight   # guest: --weight
                print(f"Session started for {session_user or 'guest'} ({calories.weight_kg:.0f} kg body weight, "
                      f"lifting {eq_label(session_equipment)})")
            if tracker.active:
                logger.keep_device_user()
            # spoken feedback - not during the start-up demo (curls then are not counted) or before logging in
            if logged_in and not demo_on:
                coach.on_events(events, feedback.counters)
                coach.on_frame(feedback.counters, drawn)
            if not tracker.active:
                du = logger.device_user()
                if du:
                    coach.on_login(du)                  # 'Hi <name>' once per 'Train on this device'
                else:
                    coach.on_logout()
            for arm, event in events:
                c_ = feedback.counters[arm]
                if c_.palm_flag_last:
                    save_snapshot(arm, frame, drawn.get(arm), "palm")
                if c_.grip_flag_last:
                    save_snapshot(arm, frame, drawn.get(arm), "grip")
                if c_.weight_flag_last:
                    save_snapshot(arm, frame, drawn.get(arm), "weight")
            # session over (walked away / stopped curling): summary + plan go to the phone page
            # someone is really there: both shoulders clearly seen (the tracker can keep a faint 'ghost'
            # skeleton for a while after the person has left, which kept the session from ending)
            present = landmarks is not None and sum(
                landmarks.landmark[i].visibility for i in (11, 12)) / 2 >= config.PRESENCE_VISIBILITY
            # for the 'nobody there' screen one clear shoulder is enough: standing close to the camera, one shoulder
            # can read unclear while the person is plainly there (15 Nov recording: 'Hi Steve' for 4.5 s)
            if landmarks is not None and max(landmarks.landmark[i].visibility for i in (11, 12)) >= \
                    config.PRESENCE_VISIBILITY:
                last_present = now
            if gate and not tracker.active and nobody_there(now, last_present):
                gate.reset()                            # walked off before starting: the next person is checked again
                demo_on = False                         # (and the guide stops: it is shown after the check)
                if nobody_there(now, last_present, config.POSITION_FORGET_SECONDS):
                    coach.on_position_reset()           # really gone: instructions may be said again to the next one
            if tracker.update(now, present, bool(events) and present):
                why = "nobody seen" if not present else "no curl"
                print(f"[SESSION] ended ({why})")
                saved_summary, saved_plan = end_session(tracker.last_activity or now)
                snaps, session_tag, session_user = [], None, None
                saved_until = now + config.SAVED_BANNER_SECONDS if saved_summary else 0.0   # nothing saved: no banner
                demo_pending = demo_allowed and gate is None    # with the position check: after it passes again
                gpio.beep()
            if demo_pending and now >= saved_until and present:
                demo_on, demo_pending, start_t = True, False, now     # next person: show the demo again

            fps_n += 1
            if now - fps_t >= 1.0:
                fps, fps_t, fps_n = fps_n / (now - fps_t), now, 0

            if not args.headless:
                if landmarks is not None:
                    PoseEngine.draw_skeleton(image, landmarks)
                shown = arm_smoother.update(drawn, now) if arm_smoother else drawn
                for arm, pts in shown.items():
                    draw_arm(image, pts, feedback.counters[arm], show_angle=args.debug_screen)
                draw_hud(image, feedback, calories.calories(now), calories.active_seconds(now), fps)
                if side:
                    side.draw_preview(image)
                if args.debug_screen:
                    draw_debug(image, feedback)
                who = session_user or logger.device_user()
                if who and not (now < saved_until):
                    cv2.putText(image, f"User: {who}", (image.shape[1] - 230, image.shape[0] - 70),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 200, 255), 2)
                if now < saved_until and saved_summary is not None:
                    draw_saved(image, saved_summary, url, (saved_plan or {}).get("goal"))
                elif not tracker.active and not demo_on and (nobody_there(now, last_present) or
                                                             (login_required and not logger.device_user())):
                    # nobody in front - or nobody logged in yet: the big QR code stays up (easier to scan;
                    # nothing starts before someone logs in anyway)
                    draw_idle(image, url, qr, logger.device_user(), login_required)
                elif not tracker.active and not demo_on and qr is not None and not logger.device_user():
                    draw_qr_corner(image, qr, url, login_required)                  # not logged in yet
                elif gate and not gate.passed and not tracker.active and not demo_on and logged_in:
                    draw_position(image, pos, gate.progress(now))                   # position check
                if session_tag is None and not demo_on and now < go_until:
                    draw_banner(image, "Good position - start curling", (0, 220, 0))
                elif drift_key and not (now < saved_until):
                    draw_banner(image, ADVICE[drift_key], (0, 200, 255))
                if tracker.active and not (now < saved_until):
                    left = tracker.countdown(now)       # only when nobody is seen or no curl for a while
                    if left is not None:
                        cv2.putText(image, f"Saving session in {left:.0f} s", (image.shape[1] // 2 - 120, 60),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 200, 255), 2)
                if demo_on and now >= saved_until:
                    el = now - start_t
                    if el >= config.DEMO_SECONDS:
                        demo_on = False
                        feedback.reset()          # anything done during the demo is not counted
                        calories.reset()
                        tracker.end()
                        snaps, session_tag = [], None
                        print("Demo finished - go!")
                        if gate and gate.passed:          # guide shown after the position check: now start
                            go_until = now + 3.0
                            coach.on_demo_done()
                    else:
                        draw_demo(image, el, config.DEMO_SECONDS - el + 0.5)
                cv2.imshow(window, fit_to_screen(image, screen) if screen else image)
                if fullscreen_pending:
                    cv2.setWindowProperty(window, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)
                    fullscreen_pending, fs_frames = False, 1
                elif fs_frames and screen is None:
                    # the window is full screen but shows the picture at its own size in the middle:
                    # screen size = picture + the margins on both sides
                    fs_frames += 1
                    x, y, iw, ih = cv2.getWindowImageRect(window)
                    if fs_frames >= 4 and x > 0 and y >= 0:
                        screen = (2 * x + iw, 2 * y + ih)
                        print(f"Full screen {screen[0]}x{screen[1]}")
                    elif fs_frames > 60:
                        fs_frames = 0                  # window manager did not make it full screen: leave it

                key = cv2.waitKey(1) & 0xFF
                if key == ord("q"):
                    break
                if key == ord("r"):
                    feedback.reset()
                    calories.reset()
                    print("Reset!")
    except KeyboardInterrupt:
        pass
    finally:
        if tracker.active:                         # program closed mid-session: still save it
            end_session(tracker.last_activity or time.time())
        voice.close()
        if pool:
            pool.shutdown(wait=False)
        stream.stop()
        engine.close()
        if hands:
            hands.close()
        gpio.off()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
