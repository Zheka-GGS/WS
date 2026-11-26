import json
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np


ROOT = Path(__file__).resolve().parent
MODEL_DIR = ROOT / "data" / "models"
MODEL_IDS = {
    "lpr_detector": "License plate detector - LPR",
    "character_recognition": "License plate OCR - Ukrainian LLDDDDLL",
    "parking_occupancy": "Parking space occupancy - PKLot",
}
MODEL_DESCRIPTIONS = {
    "lpr_detector": (
        "Detects a license plate in a vehicle image. "
        "Trained on synthetic European vehicle scenes; validate on local photos."
    ),
    "character_recognition": (
        "OCR trained on synthetic Ukrainian LLDDDDLL plates only; ELPD trains the detector, not OCR. "
        "Other European formats are unsupported, and the model score is not calibrated accuracy."
    ),
    "parking_occupancy": "Classifies a single parking space as empty or occupied.",
}
OCR_IMAGE_SIZE = (144, 48)


def _require_model(filename):
    path = MODEL_DIR / filename
    if filename == "lpr_detector.pt" and not path.is_file():
        trained_checkpoint = (
            MODEL_DIR
            / "lpr_training"
            / "license_plate_yolo"
            / "weights"
            / "best.pt"
        )
        if trained_checkpoint.is_file():
            return trained_checkpoint
    if not path.is_file():
        raise FileNotFoundError(
            f"Model {path} was not found. Run the training cells in the notebook."
        )
    return path


def _load_character_map():
    return json.loads(
        _require_model("ukrainian_lp_characters.json").read_text(encoding="utf-8")
    )


def _plate_format_status(plate):
    character_map = _load_character_map()
    plate_format = character_map.get("format")
    if plate_format != "LLDDDDLL":
        return plate_format, True

    characters = character_map["characters"]
    letters = set(characters) - set("0123456789")
    valid = (
        len(plate) == 8
        and all(char in letters for char in plate[:2] + plate[6:])
        and all(char in "0123456789" for char in plate[2:6])
    )
    return plate_format, valid


@lru_cache(maxsize=3)
def load_model(model_id):
    if model_id == "lpr_detector":
        from ultralytics import YOLO

        return YOLO(str(_require_model("lpr_detector.pt")))
    if model_id in {"character_recognition", "parking_occupancy"}:
        import tensorflow as tf

        if model_id == "character_recognition":
            return tf.keras.models.load_model(
                _require_model("ukrainian_lp_sequence_model.keras")
            )
        return tf.keras.models.load_model(
            _require_model("pklot_occupancy.keras")
        )
    raise ValueError(f"Unknown model: {model_id}")


def _predict_plate(rgb_image, model):
    if rgb_image.size == 0:
        raise ValueError("The license plate image cannot be empty.")
    resized = cv2.resize(rgb_image, OCR_IMAGE_SIZE, interpolation=cv2.INTER_LINEAR)
    grayscale = cv2.cvtColor(resized, cv2.COLOR_RGB2GRAY)
    scores = model.predict(grayscale[None, ..., None], verbose=0)[0]
    character_map = _load_character_map()
    characters = character_map["characters"]
    if scores.shape != (8, len(characters)):
        raise ValueError(
            "The OCR model output does not match the eight-character vocabulary."
        )
    indexes = np.argmax(scores, axis=1)
    plate = "".join(characters[index] for index in indexes)
    confidence = float(np.mean(np.max(scores, axis=1)))
    annotated = rgb_image.copy()
    cv2.putText(
        annotated,
        plate,
        (8, max(24, min(48, annotated.shape[0] - 4))),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.8,
        (0, 255, 0),
        2,
        cv2.LINE_AA,
    )
    return plate, confidence, annotated


def predict_model(model_id, rgb_image):
    if model_id not in MODEL_IDS:
        raise ValueError(f"Unknown model: {model_id}")
    if rgb_image is None or not isinstance(rgb_image, np.ndarray):
        raise ValueError("Upload an image to run the model.")
    if rgb_image.ndim != 3 or rgb_image.shape[2] != 3 or not rgb_image.size:
        raise ValueError("The image must be in RGB format.")

    image = np.ascontiguousarray(rgb_image, dtype=np.uint8)
    model = load_model(model_id)
    if model_id == "lpr_detector":
        result = model.predict(
            source=cv2.cvtColor(image, cv2.COLOR_RGB2BGR),
            conf=0.1,
            verbose=False,
        )[0]
        annotated = cv2.cvtColor(result.plot(), cv2.COLOR_BGR2RGB)
        if result.boxes is None or len(result.boxes) == 0:
            return annotated, "No license plate was detected."
        confidence = float(result.boxes.conf.max().cpu())
        return (
            annotated,
            f"License plate detected - confidence {confidence:.1%}. "
            "Trained on synthetic European scenes; verify on local photos.",
        )
    if model_id == "character_recognition":
        plate, confidence, annotated = _predict_plate(image, model)
        plate_format, format_valid = _plate_format_status(plate)
        if not format_valid:
            message = (
                f"OCR candidate: {plate} does not match the supported {plate_format} format. "
                "This score is not calibrated accuracy; verify the plate manually."
            )
        else:
            message = f"OCR candidate: {plate} - model score (not accuracy) {confidence:.1%}"
        return annotated, message

    input_height, input_width = model.input_shape[1:3]
    if input_height is None or input_width is None:
        raise ValueError("The PKLot model has an undefined input image size.")
    resized = cv2.resize(image, (int(input_width), int(input_height)))
    scores = model.predict(resized[None, ...], verbose=0)[0]
    label = "Empty parking space" if int(np.argmax(scores)) == 0 else "Occupied parking space"
    return None, f"{label} - confidence {float(np.max(scores)):.1%}"


def recognize_plate(rgb_image):
    if rgb_image is None or not isinstance(rgb_image, np.ndarray):
        raise ValueError("Upload a vehicle image to recognize its license plate.")
    if rgb_image.ndim != 3 or rgb_image.shape[2] != 3 or not rgb_image.size:
        raise ValueError("The vehicle image must be in RGB format.")

    detector = load_model("lpr_detector")
    result = detector.predict(
        source=cv2.cvtColor(rgb_image, cv2.COLOR_RGB2BGR),
        conf=0.1,
        verbose=False,
    )[0]
    if result.boxes is None or len(result.boxes) == 0:
        return "", 0.0, rgb_image.copy(), "No license plate was detected."

    best_index = int(result.boxes.conf.argmax().cpu())
    box = result.boxes.xyxy[best_index].cpu().numpy().astype(int)
    confidence = float(result.boxes.conf[best_index].cpu())
    height, width = rgb_image.shape[:2]
    x1, y1, x2, y2 = box.tolist()
    x1, y1 = max(0, x1), max(0, y1)
    x2, y2 = min(width, x2), min(height, y2)
    plate_crop = rgb_image[y1:y2, x1:x2]
    if plate_crop.size == 0:
        return "", confidence, rgb_image.copy(), "Could not crop the license plate."

    ocr_model = load_model("character_recognition")
    candidate, model_score, _ = _predict_plate(plate_crop, ocr_model)
    plate_format, format_valid = _plate_format_status(candidate)
    plate_text = candidate if format_valid else ""
    annotated = rgb_image.copy()
    box_thickness = max(2, round(min(width, height) / 300))
    cv2.rectangle(annotated, (x1, y1), (x2, y2), (0, 220, 70), box_thickness)
    if format_valid:
        label = f"{plate_text}  MODEL SCORE {model_score:.0%}"
    else:
        label = f"CHECK FORMAT  {candidate}  SCORE {model_score:.0%}"
    font_scale = max(0.55, min(1.0, width / 1200))
    text_thickness = max(1, round(font_scale * 2))
    (text_width, text_height), baseline = cv2.getTextSize(
        label,
        cv2.FONT_HERSHEY_SIMPLEX,
        font_scale,
        text_thickness,
    )
    label_x = min(max(x1, 0), max(0, width - text_width - 12))
    label_y = y1 - 8
    if label_y - text_height - baseline < 0:
        label_y = min(height - baseline - 4, y2 + text_height + baseline + 8)
    background_top = max(0, label_y - text_height - baseline - 6)
    background_bottom = min(height - 1, label_y + baseline + 3)
    cv2.rectangle(
        annotated,
        (label_x, background_top),
        (min(width - 1, label_x + text_width + 12), background_bottom),
        (20, 34, 48),
        cv2.FILLED,
    )
    cv2.putText(
        annotated,
        label,
        (label_x + 6, label_y),
        cv2.FONT_HERSHEY_SIMPLEX,
        font_scale,
        (255, 255, 255),
        text_thickness,
        cv2.LINE_AA,
    )
    if format_valid:
        recognition = f"OCR candidate: {plate_text} - model score (not accuracy) {model_score:.1%}"
    else:
        recognition = (
            f"OCR candidate {candidate} does not match supported {plate_format}; "
            "verify manually. Model score is not calibrated accuracy."
        )
    message = f"Plate box confidence {confidence:.1%}. {recognition}"
    return plate_text, confidence, annotated, message


def analyze_vehicle_and_space(vehicle_rgb, parking_space_rgb):
    if vehicle_rgb is None or not isinstance(vehicle_rgb, np.ndarray):
        raise ValueError("Upload a vehicle image to recognize its license plate.")
    if parking_space_rgb is None or not isinstance(parking_space_rgb, np.ndarray):
        raise ValueError("Upload a photo of one parking space.")

    if (
        vehicle_rgb.ndim != 3
        or vehicle_rgb.shape[2] != 3
        or not vehicle_rgb.size
    ):
        raise ValueError("The vehicle image must be in RGB format.")
    if (
        parking_space_rgb.ndim != 3
        or parking_space_rgb.shape[2] != 3
        or not parking_space_rgb.size
    ):
        raise ValueError("The parking-space image must be in RGB format.")

    try:
        _, _, annotated, plate_message = recognize_plate(vehicle_rgb)
    except (FileNotFoundError, ValueError) as error:
        annotated = vehicle_rgb
        plate_message = f"License-plate analysis unavailable: {error}"

    try:
        _, parking_message = predict_model("parking_occupancy", parking_space_rgb)
    except (FileNotFoundError, ValueError) as error:
        parking_message = f"Parking-space analysis unavailable: {error}"

    return annotated, plate_message, parking_message
