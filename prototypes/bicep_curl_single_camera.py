import cv2
import mediapipe as mp
import numpy as np

# ---- Setup ----
mp_pose = mp.solutions.pose
mp_drawing = mp.solutions.drawing_utils

def get_angle(a, b, c):
    a = np.array(a)
    b = np.array(b)
    c = np.array(c)
    radians = np.arctan2(c[1]-b[1], c[0]-b[0]) - \
              np.arctan2(a[1]-b[1], a[0]-b[0])
    angle = np.abs(np.degrees(radians))
    if angle > 180.0:
        angle = 360 - angle
    return round(angle, 2)

counts = {"left": 0, "right": 0}
stages = {"left": None, "right": None}

# Track form violations during a rep
form_ok = {"left": True, "right": True}

ARMS = {
    "right": {"shoulder": 12, "elbow": 14, "wrist": 16, "hip": 24, "index": 20},
    "left":  {"shoulder": 11, "elbow": 13, "wrist": 15, "hip": 23, "index": 19},
}

cap = cv2.VideoCapture(0)
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)

print("Starting... Press Q to quit, R to reset")

with mp_pose.Pose(
    min_detection_confidence=0.7,
    min_tracking_confidence=0.7) as pose:

    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            print("ERROR: Cannot read camera")
            break

        h, w = frame.shape[:2]

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        rgb.flags.writeable = False
        results = pose.process(rgb)
        rgb.flags.writeable = True

        image = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
        image = cv2.flip(image, 1)

        feedback = "Show your full arm to camera"
        feedback_color = (200, 200, 200)
        active_arm = None

        if results.pose_landmarks:
            lm = results.pose_landmarks.landmark

            for arm_name, idx in ARMS.items():
                s_idx  = idx["shoulder"]
                e_idx  = idx["elbow"]
                w_idx  = idx["wrist"]
                h_idx  = idx["hip"]
                i_idx  = idx["index"]  # fingertip for wrist straightness

                if (lm[s_idx].visibility > 0.6 and
                    lm[e_idx].visibility > 0.6 and
                    lm[w_idx].visibility > 0.6):

                    # Mirror x for display
                    shoulder = [w - int(lm[s_idx].x * w), int(lm[s_idx].y * h)]
                    elbow    = [w - int(lm[e_idx].x * w), int(lm[e_idx].y * h)]
                    wrist    = [w - int(lm[w_idx].x * w), int(lm[w_idx].y * h)]
                    hip      = [w - int(lm[h_idx].x * w), int(lm[h_idx].y * h)]
                    index    = [w - int(lm[i_idx].x * w), int(lm[i_idx].y * h)]

                    elbow_angle  = get_angle(shoulder, elbow, wrist)
                    torso_angle  = get_angle(elbow, shoulder, hip)
                    wrist_angle  = get_angle(elbow, wrist, index)  # straightness

                    # ---- Form Checks ----
                    elbow_swinging  = torso_angle > 35
                    not_extended    = stages[arm_name] == "down" and elbow_angle < 145
                    not_curled      = elbow_angle > 55  # top of curl check
                    wrist_bent      = wrist_angle < 150  # wrist curling

                    # If any form violation occurs during rep, flag it
                    if elbow_swinging or not_extended or wrist_bent:
                        form_ok[arm_name] = False

                    # ---- Rep Counting (STRICT) ----
                    if elbow_angle > 155:
                        # Bottom of rep — reset form check for new rep
                        if stages[arm_name] != "down":
                            form_ok[arm_name] = True  # fresh start each rep
                        stages[arm_name] = "down"

                    if elbow_angle < 50 and stages[arm_name] == "down":
                        stages[arm_name] = "up"
                        if form_ok[arm_name]:
                            counts[arm_name] += 1
                            print(f"✓ {arm_name.capitalize()} rep {counts[arm_name]} counted!")
                        else:
                            print(f"✗ {arm_name.capitalize()} rep NOT counted - bad form")

                    # ---- Feedback (most urgent violation first) ----
                    if (active_arm is None or
                        lm[e_idx].visibility > lm[ARMS[active_arm]["elbow"]].visibility):
                        active_arm = arm_name

                        if elbow_swinging:
                            feedback = f"{arm_name.upper()}: Keep elbow still!"
                            feedback_color = (0, 0, 255)
                        elif wrist_bent:
                            feedback = f"{arm_name.upper()}: Straighten your wrist!"
                            feedback_color = (0, 0, 255)
                        elif not_extended:
                            feedback = f"{arm_name.upper()}: Extend arm fully!"
                            feedback_color = (0, 165, 255)
                        elif stages[arm_name] == "up":
                            if form_ok[arm_name]:
                                feedback = f"{arm_name.upper()}: Good curl!"
                                feedback_color = (0, 255, 0)
                            else:
                                feedback = f"{arm_name.upper()}: Fix form - won't count!"
                                feedback_color = (0, 0, 255)
                        else:
                            feedback = f"{arm_name.upper()}: Good form!"
                            feedback_color = (0, 255, 0)

                    # Draw joints
                    # Green if form good, red if bad
                    dot_color = (0, 255, 0) if form_ok[arm_name] else (0, 0, 255)
                    cv2.circle(image, tuple(shoulder), 10, dot_color, -1)
                    cv2.circle(image, tuple(elbow),    10, dot_color, -1)
                    cv2.circle(image, tuple(wrist),    10, dot_color, -1)
                    cv2.line(image, tuple(shoulder), tuple(elbow), (255, 255, 255), 3)
                    cv2.line(image, tuple(elbow),    tuple(wrist), (255, 255, 255), 3)
                    cv2.putText(image, str(elbow_angle),
                                (elbow[0]+10, elbow[1]),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 0), 2)

                    # Show wrist angle near wrist
                    cv2.putText(image, f"W:{wrist_angle}",
                                (wrist[0]+10, wrist[1]),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 0), 1)

            # Draw skeleton (mirrored)
            flipped_landmarks = results.pose_landmarks
            for landmark in flipped_landmarks.landmark:
                landmark.x = 1.0 - landmark.x
            mp_drawing.draw_landmarks(
                image, flipped_landmarks, mp_pose.POSE_CONNECTIONS,
                mp_drawing.DrawingSpec(color=(100,100,100), thickness=1, circle_radius=1),
                mp_drawing.DrawingSpec(color=(100,100,100), thickness=1)
            )
            for landmark in flipped_landmarks.landmark:
                landmark.x = 1.0 - landmark.x

        # ---- UI ----
        cv2.rectangle(image, (0, 0), (180, 110), (20, 20, 20), -1)
        cv2.putText(image, 'RIGHT', (10, 28),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
        cv2.putText(image, str(counts["right"]), (10, 95),
                    cv2.FONT_HERSHEY_SIMPLEX, 2.8, (255, 255, 255), 3)

        cv2.rectangle(image, (w-180, 0), (w, 110), (20, 20, 20), -1)
        cv2.putText(image, 'LEFT', (w-170, 28),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 100, 255), 2)
        cv2.putText(image, str(counts["left"]), (w-170, 95),
                    cv2.FONT_HERSHEY_SIMPLEX, 2.8, (255, 255, 255), 3)

        cv2.rectangle(image, (0, 110), (180, 150), (30, 30, 30), -1)
        cv2.putText(image, stages["right"] if stages["right"] else '-',
                    (10, 142), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (200, 200, 200), 2)

        cv2.rectangle(image, (w-180, 110), (w, 150), (30, 30, 30), -1)
        cv2.putText(image, stages["left"] if stages["left"] else '-',
                    (w-170, 142), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (200, 200, 200), 2)

        # Form status indicators
        r_status = "GOOD" if form_ok["right"] else "BAD FORM"
        l_status = "GOOD" if form_ok["left"] else "BAD FORM"
        r_col = (0, 255, 0) if form_ok["right"] else (0, 0, 255)
        l_col = (0, 255, 0) if form_ok["left"] else (0, 0, 255)
        cv2.putText(image, r_status, (10, 170),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, r_col, 2)
        cv2.putText(image, l_status, (w-170, 170),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, l_col, 2)

        cv2.rectangle(image, (0, h-55), (w, h), (20, 20, 20), -1)
        cv2.putText(image, feedback, (10, h-18),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, feedback_color, 2)
        cv2.putText(image, 'Q = quit  |  R = reset', (10, h-65),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (150, 150, 150), 1)

        cv2.imshow('FitForm AI - Bicep Curl', image)

        key = cv2.waitKey(10) & 0xFF
        if key == ord('q'):
            break
        elif key == ord('r'):
            counts["left"] = counts["right"] = 0
            stages["left"] = stages["right"] = None
            form_ok["left"] = form_ok["right"] = True
            print("Reset!")

cap.release()
cv2.destroyAllWindows()
print(f"Session done. Right: {counts['right']} reps | Left: {counts['left']} reps")