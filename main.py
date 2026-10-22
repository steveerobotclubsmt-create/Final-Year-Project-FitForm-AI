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
from fitform.display_ui import draw_arm, draw_debug, draw_demo, draw_hud, draw_idle, draw_saved
from fitform.feedback_engine import FeedbackEngine
from fitform.gpio_feedback import GPIOFeedback
from fitform.hand_check import HandChecker
from fitform.pose_engine import PoseEngine
from fitform.plan import make_plan
from fitform.session import SessionTracker
from fitform.session_logger import SessionLogger, local_ip, start_server
from fitform.session_summary import build_summary, print_summary


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
    p.add_argument("--no-fist", action="store_true", help="do not require a clenched fist")
    p.add_argument("--no-palm", action="store_true", help="turn off the palm-direction check")
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
    if args.angles:
        config.USE_3D_ANGLES = args.angles == "3d"
    print(f"Angles: {'3D' if config.USE_3D_ANGLES else '2D'} | straight above {config.DOWN_ANGLE} | "
          f"curled below {config.UP_ANGLE} | palm check {'on' if config.PALM_CHECK else 'off'} | "
          f"fist check {'on' if config.FIST_CHECK else 'off'} | lift {config.MIN_UP_SECONDS}-{config.MAX_UP_SECONDS} s")
    hands = HandChecker() if (config.FIST_CHECK or config.PALM_CHECK) else None
    calories = CalorieTracker(weight_kg=args.weight)
    gpio = GPIOFeedback(enabled=not args.no_gpio and config.GPIO_ENABLED)
    logger = SessionLogger()
    if config.FLASK_ENABLED and not args.no_server:
        start_server(logger)

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
    demo_on = demo_allowed
    demo_pending = False
    tracker = SessionTracker()
    snaps, session_tag = [], None
    saved_until, saved_summary, saved_plan = 0.0, None, None
    url = f"http://{local_ip()}:{config.FLASK_PORT}" if (config.FLASK_ENABLED and not args.no_server) else logger.dir
    print(f"Phone page: {url}")

    session_user = None
    qr = None
    try:
        qr = cv2.QRCodeEncoder.create().encode(url) if url.startswith("http") else None
    except (AttributeError, cv2.error):
        qr = None

    def end_session(end_time):
        """Session over: summary + goal for next time, saved to the user's account; device logs out."""
        summary = build_summary(feedback, calories, end_time, snapshots=snaps, user=session_user)
        plan = make_plan(summary, logger.history(session_user or "guest"), calories.weight_kg)
        print_summary(summary, plan)
        logger.save(summary, plan)
        logger.clear_device_user()
        feedback.reset()
        calories.reset()
        tracker.end()
        return summary, plan

    def save_snapshot(arm, frame, pts, kind):
        """Picture of the hand (front camera, plus the side camera) for the turned-out-fist warning."""
        if len(snaps) >= config.MAX_SNAPSHOTS or pts is None:
            return
        x, y = int(pts["wrist"][0]), int(pts["wrist"][1])
        r = 120
        crop = frame[max(0, y - r):y + r, max(0, x - r):x + r]
        if crop.size == 0:
            return
        crop = cv2.resize(cv2.flip(crop, 1), (240, 240))     # mirrored, like the screen
        if side is not None and arm == args.side_arm and side.frame is not None:
            sf = side.frame
            crop = cv2.hconcat([crop, cv2.resize(sf, (int(240 * sf.shape[1] / sf.shape[0]), 240))])
        os.makedirs(logger.snap_dir, exist_ok=True)
        name = f"{session_tag}_{arm}_{kind}_{len(snaps) + 1}.jpg"
        cv2.imwrite(os.path.join(logger.snap_dir, name), crop)
        snaps.append(name)

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
                                            side_palms={args.side_arm: side.label} if side else None)
            if args.debug and now - last_dbg >= 0.5:
                last_dbg = now
                print(f"FPS {fps:.1f}")
                for arm in drawn:
                    c = feedback.counters[arm]; d = c.last
                    fmt = lambda v: "-" if v is None else f"{v:.0f}"
                    ps = hands.palm_scores.get(arm) if hands else None
                    lr = d.get('len_ratio')
                    print(f"[{arm[0].upper()}] elbow {fmt(d['elbow_angle'])} (2D {fmt(d.get('elbow2d'))} / "
                          f"3D {fmt(d.get('elbow3d'))}) drift {fmt(d['drift'])} tilt {fmt(d.get('tilt'))} "
                          f"len {'-' if lr is None else f'{lr:.2f}'} wrist {fmt(d['wrist_angle'])} "
                          f"hand {d['hand'] or '-'}{'' if not hands or hands.curls.get(arm) is None else f' ({hands.curls[arm]}/4 fingers)'} palm {d.get('palm') or '-'}"
                          f"{'' if ps is None else f' (front {ps[0]:+.2f} inward {ps[1]:+.2f})'}"
                          f"{f' side {side.label or chr(45)} ({side.score:+.2f})' if (side and arm == args.side_arm and side.score is not None) else ''}"
                          f"{' FORESHORTENED' if d.get('foreshortened') else ''} stage {c.stage or '-'} ready {c.ready}")
            for arm, event in events:
                cnt = feedback.counters[arm]
                ut = cnt.last_up_time
                lift = f" (lift {ut:.1f} s" + (f", {cnt.last_hand_summary}" if cnt.last_hand_summary else "") + ")" \
                    if ut is not None else ""
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
                calories.weight_kg = logger.user_weight(session_user) if session_user else config.USER_WEIGHT_KG
                print(f"Session started for {session_user or 'guest'} ({calories.weight_kg:.0f} kg)")
            if tracker.active:
                logger.keep_device_user()
            for arm, event in events:
                c_ = feedback.counters[arm]
                if c_.palm_flag_last:
                    save_snapshot(arm, frame, drawn.get(arm), "palm")
                if c_.grip_flag_last:
                    save_snapshot(arm, frame, drawn.get(arm), "grip")
            # session over (walked away / stopped curling): summary + plan go to the phone page
            if tracker.update(now, landmarks is not None, bool(events)):
                saved_summary, saved_plan = end_session(tracker.last_activity or now)
                snaps, session_tag, session_user = [], None, None
                saved_until = now + config.SAVED_BANNER_SECONDS
                demo_pending = demo_allowed
                gpio.beep()
            if demo_pending and now >= saved_until and landmarks is not None:
                demo_on, demo_pending, start_t = True, False, now     # next person: show the demo again

            fps_n += 1
            if now - fps_t >= 1.0:
                fps, fps_t, fps_n = fps_n / (now - fps_t), now, 0

            if not args.headless:
                if landmarks is not None:
                    PoseEngine.draw_skeleton(image, landmarks)
                for arm, pts in drawn.items():
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
                elif not tracker.active and not demo_on and landmarks is None:     # nobody in front
                    draw_idle(image, url, qr, logger.device_user())
                if demo_on and now >= saved_until:
                    el = now - start_t
                    if el >= config.DEMO_SECONDS:
                        demo_on = False
                        feedback.reset()          # anything done during the demo is not counted
                        calories.reset()
                        tracker.end()
                        snaps, session_tag = [], None
                        print("Demo finished - go!")
                    else:
                        draw_demo(image, el, config.DEMO_SECONDS - el + 0.5)
                cv2.imshow("FitForm AI - Bicep Curl", image)

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
