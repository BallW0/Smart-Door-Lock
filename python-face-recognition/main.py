"""
Smart Door Lock - Face Recognition Main Script
================================================
Uses OpenCV Haar Cascade face detection + LBPH face recognizer.
Connects to an ESP32-CAM MJPEG stream, recognizes known faces,
and triggers the door lock via HTTP POST requests.

Requirements:
    pip install opencv-python opencv-contrib-python numpy requests

Directory structure:
    known_faces/
        PersonName1/
            face_001.jpg
            face_002.jpg
            ...
        PersonName2/
            face_001.jpg
            ...
    trained_model.yml   (auto-generated after first training)
    label_map.json      (auto-generated after first training)

Author: Smart Door Lock Project
Date: 2026
"""

import cv2
import numpy as np
import os
import sys
import json
import time
import logging
import requests
import signal
from pathlib import Path
from datetime import datetime

# ==============================================================================
# USER CONFIGURATION — Edit these values to match your setup
# ==============================================================================
ESP32_CAM_IP          = '10.206.32.203'        # Change to your ESP32-CAM IP address
API_URL               = 'http://localhost:3000' # Node.js backend API base URL
KNOWN_FACES_DIR       = 'known_faces'           # Directory containing sub-folders per person
CONFIDENCE_THRESHOLD  = 80                      # LBPH confidence: lower = stricter match
COOLDOWN_SECONDS      = 10                      # Minimum seconds between door-unlock signals
CAMERA_STREAM_URL     = f'http://{ESP32_CAM_IP}/stream'  # ESP32-CAM MJPEG stream URL
STREAM_RETRY_DELAY    = 3                       # Seconds to wait before retrying stream
TRAINED_MODEL_FILE    = os.path.join(KNOWN_FACES_DIR, 'trained_model.yml')
LABEL_MAP_FILE        = os.path.join(KNOWN_FACES_DIR, 'label_map.json')
WINDOW_TITLE          = 'Smart Door Lock - Face Recognition'
# ==============================================================================

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)-8s %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('face_recognition.log', encoding='utf-8'),
    ]
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Graceful shutdown flag
# ---------------------------------------------------------------------------
_shutdown_requested = False

def _handle_signal(signum, frame):
    """Handle SIGINT (Ctrl+C) and SIGTERM gracefully."""
    global _shutdown_requested
    log.info("Shutdown signal received. Stopping gracefully...")
    _shutdown_requested = True

signal.signal(signal.SIGINT,  _handle_signal)
signal.signal(signal.SIGTERM, _handle_signal)


# ==============================================================================
# CORE FUNCTIONS
# ==============================================================================

def print_banner():
    """Print a startup banner to the console."""
    banner = """
╔══════════════════════════════════════════════════════════════╗
║          SMART DOOR LOCK — Face Recognition System           ║
║          OpenCV Haar Cascade + LBPH Face Recognizer          ║
╠══════════════════════════════════════════════════════════════╣
║  Press  Q   → Quit                                           ║
║  Press  R   → Reload / Retrain recognizer                    ║
╚══════════════════════════════════════════════════════════════╝
"""
    print(banner)


def check_esp32_cam_reachable(esp32_cam_ip: str, timeout: int = 5) -> bool:
    """
    Perform a quick HTTP GET to verify the ESP32-CAM is reachable on the network.

    Args:
        esp32_cam_ip: IP address of the ESP32-CAM.
        timeout:      Request timeout in seconds.

    Returns:
        True if the camera responded with any HTTP status, False otherwise.
    """
    url = f'http://{esp32_cam_ip}/'
    log.info(f"Checking ESP32-CAM reachability at {url} ...")
    try:
        response = requests.get(url, timeout=timeout)
        log.info(f"ESP32-CAM responded with HTTP {response.status_code}.")
        return True
    except requests.exceptions.ConnectionError:
        log.warning(f"ESP32-CAM at {esp32_cam_ip} is NOT reachable (ConnectionError).")
        return False
    except requests.exceptions.Timeout:
        log.warning(f"ESP32-CAM at {esp32_cam_ip} is NOT reachable (Timeout).")
        return False
    except requests.exceptions.RequestException as exc:
        log.warning(f"ESP32-CAM check failed: {exc}")
        return False


def load_and_train_recognizer(faces_dir: str):
    """
    Load all known face images, train an LBPH recognizer, and return the
    trained objects.  If a pre-saved model exists it is loaded directly for
    faster startup.

    Args:
        faces_dir: Path to the root known_faces directory.

    Returns:
        Tuple of:
            face_cascade  — cv2.CascadeClassifier (Haar frontal face)
            recognizer    — cv2.face.LBPHFaceRecognizer (trained) or None
            label_map     — dict {int label_id: str person_name}
    """
    # ── Haar Cascade ──────────────────────────────────────────────────────────
    haar_path = cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
    face_cascade = cv2.CascadeClassifier(haar_path)
    if face_cascade.empty():
        log.error(f"Failed to load Haar Cascade from: {haar_path}")
        sys.exit(1)
    log.info("Haar Cascade classifier loaded successfully.")

    # ── Try loading pre-saved model ───────────────────────────────────────────
    trained_model_path = os.path.join(faces_dir, 'trained_model.yml')
    label_map_path     = os.path.join(faces_dir, 'label_map.json')

    if os.path.isfile(trained_model_path) and os.path.isfile(label_map_path):
        log.info("Pre-saved model found. Loading trained_model.yml and label_map.json ...")
        recognizer = cv2.face.LBPHFaceRecognizer_create()
        recognizer.read(trained_model_path)
        with open(label_map_path, 'r', encoding='utf-8') as fh:
            raw_map = json.load(fh)
        # JSON keys are strings; convert back to int
        label_map = {int(k): v for k, v in raw_map.items()}
        log.info(f"Model loaded. Known persons: {list(label_map.values())}")
        return face_cascade, recognizer, label_map

    # ── Train from scratch ────────────────────────────────────────────────────
    log.info("No pre-saved model found. Training from scratch ...")

    faces_root = Path(faces_dir)
    if not faces_root.is_dir():
        log.warning(f"Directory '{faces_dir}' does not exist. "
                    "No recognizer will be created.")
        return face_cascade, None, {}

    face_samples  = []   # list of grayscale numpy arrays
    labels        = []   # corresponding int label IDs
    label_map     = {}   # {label_id: person_name}
    current_label = 0

    # Each sub-directory is one person
    person_dirs = sorted([p for p in faces_root.iterdir() if p.is_dir()])

    if not person_dirs:
        log.warning(f"No person sub-directories found in '{faces_dir}'. "
                    "Add sub-folders with face images to train the model.")
        return face_cascade, None, {}

    for person_dir in person_dirs:
        person_name  = person_dir.name
        image_paths  = list(person_dir.glob('*.jpg')) + \
                       list(person_dir.glob('*.jpeg')) + \
                       list(person_dir.glob('*.png'))

        if not image_paths:
            log.warning(f"No images found for '{person_name}'. Skipping.")
            continue

        log.info(f"Processing '{person_name}' — {len(image_paths)} image(s) ...")
        label_map[current_label] = person_name
        images_added = 0

        for img_path in image_paths:
            img = cv2.imread(str(img_path))
            if img is None:
                log.warning(f"  Could not read image: {img_path}")
                continue

            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

            # Detect face in the training image
            detected_faces = face_cascade.detectMultiScale(
                gray,
                scaleFactor=1.1,
                minNeighbors=5,
                minSize=(60, 60)
            )

            if len(detected_faces) == 0:
                # If cascade finds nothing, use the whole image resized
                face_roi = cv2.resize(gray, (200, 200))
            else:
                # Use the largest detected face
                x, y, w, h = max(detected_faces, key=lambda r: r[2] * r[3])
                face_roi = cv2.resize(gray[y:y + h, x:x + w], (200, 200))

            face_samples.append(face_roi)
            labels.append(current_label)
            images_added += 1

        log.info(f"  Added {images_added} face sample(s) for '{person_name}'.")
        current_label += 1

    if not face_samples:
        log.warning("No usable face samples collected. Recognizer will not be created.")
        return face_cascade, None, {}

    # ── Train LBPH recognizer ─────────────────────────────────────────────────
    recognizer = cv2.face.LBPHFaceRecognizer_create()
    recognizer.train(face_samples, np.array(labels))
    log.info(f"LBPH recognizer trained on {len(face_samples)} samples "
             f"across {len(label_map)} person(s).")

    # ── Persist model to disk ─────────────────────────────────────────────────
    os.makedirs(faces_dir, exist_ok=True)
    recognizer.save(trained_model_path)
    with open(label_map_path, 'w', encoding='utf-8') as fh:
        json.dump(label_map, fh, indent=2, ensure_ascii=False)
    log.info(f"Model saved → {trained_model_path}")
    log.info(f"Label map saved → {label_map_path}")

    return face_cascade, recognizer, label_map


def send_face_detected_api(api_url: str) -> bool:
    """
    Send an HTTP POST to the Node.js API /face-recognized endpoint.
    The ESP32 DevKit will poll this API and unlock the door.

    Args:
        api_url: Base URL of the Node.js API.

    Returns:
        True if the API responded with HTTP 200, False otherwise.
    """
    try:
        url = f'{api_url}/api/system/face-recognized'
        log.info(f"Sending face-detected signal to API → {url}")
        response = requests.post(url, json={'recognized': True}, timeout=3)
        if response.status_code == 200:
            log.info("Face detected flag set on Node.js API.")
            return True
        else:
            log.warning(f"API responded with unexpected status: HTTP {response.status_code}")
            return False
    except requests.exceptions.RequestException as exc:
        log.error(f"API face-detected request failed: {exc}")
        return False


def log_to_api(api_url: str, user_name: str, status: str = 'granted') -> None:
    """
    POST an access-log entry to the Node.js backend API.

    Args:
        api_url:   Base URL of the Node.js API (e.g. 'http://localhost:3000').
        user_name: Name of the recognized person (or 'Unknown').
        status:    Access status string, e.g. 'granted' or 'denied'.
    """
    endpoint = f'{api_url}/api/logs'
    payload = {
        'method':  'face',
        'status':  status,
        'user':    user_name,
        'details': f'Face recognition: {status}',
    }
    try:
        response = requests.post(endpoint, json=payload, timeout=3)
        log.info(f"API log posted → {endpoint} | user='{user_name}' "
                 f"status='{status}' | HTTP {response.status_code}")
    except requests.exceptions.RequestException as exc:
        # Non-fatal: silently ignore API logging errors
        log.debug(f"API logging failed (ignored): {exc}")


def draw_face_annotation(
    frame: np.ndarray,
    x: int, y: int, w: int, h: int,
    label: str,
    confidence: float,
    recognized: bool
) -> None:
    """
    Draw a bounding rectangle and label text on the video frame.

    Green rectangle + name  → recognized person.
    Red rectangle + Unknown → unrecognized face.

    Args:
        frame:      BGR image frame to draw on (in-place).
        x, y, w, h: Bounding box of the detected face.
        label:      Display name for the face.
        confidence: LBPH confidence score (lower = better).
        recognized: True if the face matched a known person.
    """
    color       = (0, 255, 0) if recognized else (0, 0, 255)
    text_color  = (255, 255, 255)
    box_thick   = 2
    font        = cv2.FONT_HERSHEY_SIMPLEX
    font_scale  = 0.65
    font_thick  = 2

    # Bounding box
    cv2.rectangle(frame, (x, y), (x + w, y + h), color, box_thick)

    # Label background fill
    conf_str   = f'{confidence:.1f}'
    display    = f'{label}  [{conf_str}]'
    (tw, th), baseline = cv2.getTextSize(display, font, font_scale, font_thick)
    bg_y1 = max(y - th - baseline - 6, 0)
    bg_y2 = max(y, th + baseline + 6)
    cv2.rectangle(frame, (x, bg_y1), (x + tw + 6, bg_y2), color, cv2.FILLED)

    # Label text
    cv2.putText(
        frame, display,
        (x + 3, max(y - baseline - 2, th + 2)),
        font, font_scale, text_color, font_thick, cv2.LINE_AA
    )


def draw_status_overlay(frame: np.ndarray, status_lines: list) -> None:
    """
    Draw a small status overlay in the top-right corner of the frame.

    Args:
        frame:        BGR image frame to draw on (in-place).
        status_lines: List of strings to display.
    """
    font        = cv2.FONT_HERSHEY_SIMPLEX
    font_scale  = 0.45
    font_thick  = 1
    padding     = 6
    line_height = 18
    fh, fw      = frame.shape[:2]

    for i, line in enumerate(status_lines):
        y_pos = padding + (i + 1) * line_height
        # Shadow
        cv2.putText(frame, line, (fw - 260 + 1, y_pos + 1),
                    font, font_scale, (0, 0, 0), font_thick + 1, cv2.LINE_AA)
        # Text
        cv2.putText(frame, line, (fw - 260, y_pos),
                    font, font_scale, (200, 255, 200), font_thick, cv2.LINE_AA)


# ==============================================================================
# MAIN ENTRY POINT
# ==============================================================================

def main():
    """
    Main execution loop for the Smart Door Lock face recognition system.

    Flow:
      1. Print banner and check ESP32-CAM reachability.
      2. Load / train face recognizer.
      3. Connect to ESP32-CAM MJPEG stream (retry if unavailable).
      4. For each video frame:
         - Detect faces with Haar Cascade.
         - Predict identity with LBPH recognizer.
         - Annotate frame (green = known, red = unknown).
         - Trigger door unlock + log event on successful recognition.
      5. Handle 'q' (quit) and 'r' (retrain) key presses.
      6. Release resources on exit.
    """
    global _shutdown_requested

    print_banner()

    # ── Startup check ─────────────────────────────────────────────────────────
    cam_reachable = check_esp32_cam_reachable(ESP32_CAM_IP)
    if not cam_reachable:
        log.warning("ESP32-CAM is not reachable. The stream will likely fail. "
                    "Continuing anyway — retries are built in.")

    # ── Load / train recognizer ───────────────────────────────────────────────
    log.info("Initializing face recognizer ...")
    face_cascade, recognizer, label_map = load_and_train_recognizer(KNOWN_FACES_DIR)

    if recognizer is None:
        log.warning("Recognizer is not available. "
                    "All detected faces will be labeled as 'Unknown'.")
    else:
        log.info(f"Recognizer ready. Known persons: {list(label_map.values())}")

    # ── State variables ───────────────────────────────────────────────────────
    last_detection_time = 0.0   # Epoch seconds of last successful unlock
    cap                 = None  # cv2.VideoCapture handle

    # ── Stream connection loop ────────────────────────────────────────────────
    def connect_stream() -> cv2.VideoCapture:
        """Attempt to open the ESP32-CAM MJPEG stream, retrying until success."""
        attempt = 0
        while not _shutdown_requested:
            attempt += 1
            log.info(f"Connecting to stream (attempt {attempt}): {CAMERA_STREAM_URL}")
            cap_handle = cv2.VideoCapture(CAMERA_STREAM_URL)
            if cap_handle.isOpened():
                log.info("Stream connected successfully.")
                return cap_handle
            log.warning(f"Failed to open stream. Retrying in {STREAM_RETRY_DELAY}s ...")
            cap_handle.release()
            time.sleep(STREAM_RETRY_DELAY)
        return None

    cap = connect_stream()
    if cap is None:
        log.info("Stream connection aborted by shutdown signal.")
        return

    log.info("Entering main recognition loop. Press 'Q' to quit, 'R' to retrain.")

    # ── Main recognition loop ─────────────────────────────────────────────────
    consecutive_read_failures = 0
    MAX_CONSECUTIVE_FAILURES  = 30  # ~1 second at 30fps before reconnect
    
    last_model_check_time = time.time()

    while not _shutdown_requested:
        # Check for auto-retrain trigger from Web API (missing trained_model.yml)
        if time.time() - last_model_check_time > 3.0:
            last_model_check_time = time.time()
            if not os.path.exists(TRAINED_MODEL_FILE):
                log.info("Auto-retrain triggered: trained_model.yml is missing.")
                face_cascade, recognizer, label_map = load_and_train_recognizer(KNOWN_FACES_DIR)
                if recognizer is not None:
                    log.info(f"Auto-retrain complete. Known persons: {list(label_map.values())}")
                else:
                    log.warning("Auto-retrain failed (no faces found).")

        ret, frame = cap.read()

        # ── Handle read failure / stream drop ─────────────────────────────────
        if not ret or frame is None:
            consecutive_read_failures += 1
            log.warning(f"Frame read failed ({consecutive_read_failures}/"
                        f"{MAX_CONSECUTIVE_FAILURES}).")
            if consecutive_read_failures >= MAX_CONSECUTIVE_FAILURES:
                log.error("Too many consecutive read failures. Reconnecting ...")
                cap.release()
                cap = connect_stream()
                if cap is None:
                    break
                consecutive_read_failures = 0
            time.sleep(0.05)
            continue

        consecutive_read_failures = 0

        # ── Convert to grayscale for detection ────────────────────────────────
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        # Histogram equalisation improves detection under varying lighting
        gray = cv2.equalizeHist(gray)

        # ── Haar Cascade face detection ───────────────────────────────────────
        detected_faces = face_cascade.detectMultiScale(
            gray,
            scaleFactor=1.3,
            minNeighbors=5,
            minSize=(80, 80)
        )

        now             = time.time()
        cooldown_left   = max(0.0, COOLDOWN_SECONDS - (now - last_detection_time))
        in_cooldown     = cooldown_left > 0

        # ── Process each detected face ─────────────────────────────────────────
        for (x, y, w, h) in detected_faces:
            face_roi    = cv2.resize(gray[y:y + h, x:x + w], (200, 200))
            label_id    = -1
            confidence  = 999.0
            recognized  = False
            person_name = 'Unknown'

            if recognizer is not None:
                label_id, confidence = recognizer.predict(face_roi)
                if confidence < CONFIDENCE_THRESHOLD:
                    recognized  = True
                    person_name = label_map.get(label_id, 'Unknown')

            # ── Draw annotation ────────────────────────────────────────────────
            draw_face_annotation(frame, x, y, w, h,
                                 person_name, confidence, recognized)

            # ── Trigger unlock + log on recognition (respecting cooldown) ──────
            if recognized and not in_cooldown:
                log.info(f"RECOGNIZED: '{person_name}' "
                         f"(confidence={confidence:.2f}) — triggering unlock.")
                signal_ok = send_face_detected_api(API_URL)
                
                if signal_ok:
                    log_to_api(API_URL, person_name, status='granted')
                else:
                    log.warning("Door signal failed; access event NOT logged to database.")
                    
                last_detection_time = time.time()
                in_cooldown         = True
                cooldown_left       = float(COOLDOWN_SECONDS)
                
            elif recognized and in_cooldown:
                log.debug(f"'{person_name}' recognized but in cooldown "
                          f"({cooldown_left:.1f}s remaining).")

        # ── Status overlay ─────────────────────────────────────────────────────
        ts_str = datetime.now().strftime('%H:%M:%S')
        n_known = len(label_map)
        status_lines = [
            f'Time : {ts_str}',
            f'Known: {n_known} person(s)',
            f'Threshold: {CONFIDENCE_THRESHOLD}',
            f'Cooldown : {cooldown_left:.1f}s' if in_cooldown else 'Cooldown : -',
            f'Faces: {len(detected_faces)}',
        ]
        draw_status_overlay(frame, status_lines)

        # ── Show frame ─────────────────────────────────────────────────────────
        cv2.imshow(WINDOW_TITLE, frame)

        # ── Key handling ───────────────────────────────────────────────────────
        key = cv2.waitKey(1) & 0xFF

        if key == ord('q') or key == ord('Q'):
            log.info("'Q' pressed — shutting down.")
            _shutdown_requested = True
            break

        if key == ord('r') or key == ord('R'):
            log.info("'R' pressed — reloading and retraining recognizer ...")
            face_cascade, recognizer, label_map = load_and_train_recognizer(
                KNOWN_FACES_DIR
            )
            if recognizer is None:
                log.warning("Recognizer reload returned None (no training data).")
            else:
                log.info(f"Recognizer reloaded. "
                         f"Known persons: {list(label_map.values())}")

        # Allow OpenCV window close button to exit
        if cv2.getWindowProperty(WINDOW_TITLE, cv2.WND_PROP_VISIBLE) < 1:
            log.info("Window closed by user.")
            _shutdown_requested = True
            break

    # ── Cleanup ────────────────────────────────────────────────────────────────
    log.info("Releasing resources ...")
    if cap is not None:
        cap.release()
    cv2.destroyAllWindows()
    log.info("Smart Door Lock face recognition system stopped.")


if __name__ == '__main__':
    main()
