"""FitForm AI - entry point (single camera).

Examples:
  python main.py                      # default webcam (index 0)
  python main.py --camera 1           # a different camera
  python main.py --video test.mp4     # run on a recorded video instead of a camera
  python main.py --weight 65          # set body weight for the calorie estimate
"""

import argparse
import time

import cv2

from fitform import config
from fitform.calorie_tracker import CalorieTracker
from fitform.camera_thread import CameraStream
from fitform.display_ui import draw_arm, draw_hud
from fitform.feedback_engine import FeedbackEngine
from fitform.gpio_feedback import GPIOFeedback
from fitform.pose_engine import PoseEngine
from fitform.session_logger import SessionLogger, start_server
from fitform.session_summary import build_summary, print_summary


def parse_args():
    p = argparse.ArgumentParser(description="FitForm AI - bicep curl trainer")
    p.add_argument("--camera", type=int, default=config.CAMERA_INDEX, help="camera index (default 0)")
    p.add_argument("--video", help="video file to use instead of a camera")
    p.add_argument("--weight", type=float, default=config.USER_WEIGHT_KG, help="body weight in kg")
    p.add_argument("--no-gpio", action="store_true", help="disable LEDs/buzzer")
    p.add_argument("--no-server", action="store_true", help="disable the Flask web server")
    p.add_argument("--headless", action="store_true", help="no window (for testing)")
    return p.parse_args()


def main():
    args = parse_args()
    W, H = config.DISPLAY_WIDTH, config.DISPLAY_HEIGHT

    source = args.video if args.video else args.camera
    stream = CameraStream(source, config.CAPTURE_WIDTH, config.CAPTURE_HEIGHT)
    if not stream.is_opened():
        print(f"ERROR: could not open {source!r}. Try another camera with --camera 1")
        return
    stream.start()

    engine = PoseEngine()
    feedback = FeedbackEngine()
    calories = CalorieTracker(weight_kg=args.weight)
    gpio = GPIOFeedback(enabled=not args.no_gpio and config.GPIO_ENABLED)
    logger = SessionLogger()
    if config.FLASK_ENABLED and not args.no_server:
        start_server(logger)

    print("Starting... Press Q to quit, R to reset")
    last_id = -1
    fps, fps_t, fps_n = 0.0, time.time(), 0

    try:
        while not stream.finished:
            frame_id, frame = stream.read()
            if frame is None or frame_id == last_id:
                time.sleep(0.002)
                continue
            last_id = frame_id

            now = time.time()
            frame = cv2.resize(frame, (W, H))
            landmarks = engine.process(frame)      # detect on the un-mirrored frame
            image = cv2.flip(frame, 1)             # show mirrored, like a mirror

            events, drawn = feedback.update(landmarks, W, H, now)
            for arm, event in events:
                if event == "counted":
                    calories.on_rep(now)
                    gpio.beep()
                    print(f"+ {arm.capitalize()} rep {feedback.counters[arm].count} counted")
                else:
                    print(f"x {arm.capitalize()} rep NOT counted - bad form")
            gpio.show_form(feedback.overall_form_ok())

            fps_n += 1
            if now - fps_t >= 1.0:
                fps, fps_t, fps_n = fps_n / (now - fps_t), now, 0

            if not args.headless:
                if landmarks is not None:
                    PoseEngine.draw_skeleton(image, landmarks)
                for arm, pts in drawn.items():
                    draw_arm(image, pts, feedback.counters[arm])
                draw_hud(image, feedback, calories.calories(now), calories.active_seconds(now), fps)
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
        stream.stop()
        engine.close()
        gpio.off()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
