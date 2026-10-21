"""FitForm AI - entry point (single camera).

Examples:
  python main.py                      # default webcam (index 0)
  python main.py --camera 1           # a different camera
  python main.py --camera picam       # Raspberry Pi Camera Module (via rpicam-vid)
  python main.py --video test.mp4     # run on a recorded video instead of a camera
  python main.py --weight 65          # set body weight for the calorie estimate
  python main.py --debug --angles 2d  # print live angles; compare 2D and 3D elbow angles
  python main.py --camera picam --rotate 180   # camera mounted upside down
"""

import argparse
import time

import cv2

from fitform import config
from fitform.calorie_tracker import CalorieTracker
from fitform.camera_thread import CameraStream
from fitform.display_ui import draw_arm, draw_debug, draw_hud
from fitform.feedback_engine import FeedbackEngine
from fitform.gpio_feedback import GPIOFeedback
from fitform.hand_check import HandChecker
from fitform.pose_engine import PoseEngine
from fitform.session_logger import SessionLogger, start_server
from fitform.session_summary import build_summary, print_summary


def parse_args():
    p = argparse.ArgumentParser(description="FitForm AI - bicep curl trainer")
    p.add_argument("--camera", default=str(config.CAMERA_INDEX),
                   help="camera index (0, 1, ...) or 'picam' for the Pi Camera Module (default 0)")
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
    p.add_argument("--rotate", type=int, choices=[0, 90, 180, 270], default=0,
                   help="rotate the camera picture (e.g. 180 for a camera mounted upside down)")
    return p.parse_args()


def main():
    args = parse_args()
    W, H = config.DISPLAY_WIDTH, config.DISPLAY_HEIGHT

    if args.video:
        source = args.video
    elif args.camera.lower() == "picam":
        source = "picam"
    else:
        source = int(args.camera)
    stream = CameraStream(source, config.CAPTURE_WIDTH, config.CAPTURE_HEIGHT)
    if not stream.is_opened():
        print(f"ERROR: could not open {source!r}. Try another camera with --camera 1 "
              "(or --camera picam for the Pi Camera Module; check it with: rpicam-hello --list-cameras)")
        return
    stream.start()

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

    pool = None
    if hands and config.PARALLEL_HANDS:
        from concurrent.futures import ThreadPoolExecutor
        pool = ThreadPoolExecutor(max_workers=1)
    prev_landmarks = None
    cam_w = int(stream.cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    cam_h = int(stream.cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    print(f"Camera {cam_w}x{cam_h}, processing {W}x{H}, pose model {config.MODEL_COMPLEXITY}, "
          f"hands every {config.HAND_EVERY_N} frame(s){' in parallel' if pool else ''}")
    print("Starting... Press Q to quit, R to reset")
    last_id = -1
    rotate_code = {90: cv2.ROTATE_90_CLOCKWISE, 180: cv2.ROTATE_180,
                   270: cv2.ROTATE_90_COUNTERCLOCKWISE}.get(args.rotate)
    last_dbg = 0.0
    fps, fps_t, fps_n = 0.0, time.time(), 0

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
            if hands and pool:
                # hands run on a second core at the same time as pose; they are matched to the arms
                # using the pose from the previous frame (the arm hardly moves in 1/15 s)
                hand_job = pool.submit(hands.process, frame, prev_landmarks)
                landmarks = engine.process(frame)  # detect on the un-mirrored frame
                hand_states = hand_job.result()
            else:
                landmarks = engine.process(frame)
                hand_states = hands.process(frame, landmarks) if hands else None
            prev_landmarks = landmarks
            image = cv2.flip(frame, 1)             # show mirrored, like a mirror
            events, drawn = feedback.update(landmarks, W, H, now, world=engine.world, hands=hand_states,
                                            hand_points=hands.points if hands else None,
                                            palms=hands.palms if hands else None)
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
                          f"hand {d['hand'] or '-'} palm {d.get('palm') or '-'}"
                          f"{'' if ps is None else f' (front {ps[0]:+.2f} inward {ps[1]:+.2f})'} stage {c.stage or '-'} ready {c.ready}")
            for arm, event in events:
                cnt = feedback.counters[arm]
                ut = cnt.last_up_time
                lift = f" (lift {ut:.1f} s" + (f", {cnt.last_hand_summary}" if cnt.last_hand_summary else "") + ")" \
                    if ut is not None else ""
                if event == "counted":
                    calories.on_rep(now)
                    gpio.beep()
                    print(f"+ {arm.capitalize()} rep {feedback.counters[arm].count} counted{lift}")
                else:
                    why = ", ".join(feedback.counters[arm].last_reasons) or "bad form"
                    print(f"x {arm.capitalize()} rep NOT counted - {why}{lift}")
            gpio.show_form(feedback.overall_form_ok())

            fps_n += 1
            if now - fps_t >= 1.0:
                fps, fps_t, fps_n = fps_n / (now - fps_t), now, 0

            if not args.headless:
                if landmarks is not None:
                    PoseEngine.draw_skeleton(image, landmarks)
                for arm, pts in drawn.items():
                    draw_arm(image, pts, feedback.counters[arm], show_angle=args.debug_screen)
                draw_hud(image, feedback, calories.calories(now), calories.active_seconds(now), fps)
                if args.debug_screen:
                    draw_debug(image, feedback)
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
        now = time.time()
        summary = build_summary(feedback, calories, now)
        print_summary(summary)
        if summary["attempted_total"] > 0:
            logger.save(summary)
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
