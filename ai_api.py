import base64
import time
from io import BytesIO

import numpy as np
from fastapi import FastAPI, File, HTTPException, UploadFile
from PIL import Image, UnidentifiedImageError

from model_inference import (
    MODEL_DESCRIPTIONS,
    MODEL_IDS,
    predict_model,
    recognize_plate,
)


MAX_IMAGE_BYTES = 10 * 1024 * 1024
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}


app = FastAPI(title="ParkVision AI API", version="1.0.0")


async def read_rgb_image(file: UploadFile):
    if file.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=415,
            detail="Підтримуються лише JPEG, PNG та WebP.",
        )
    content = await file.read(MAX_IMAGE_BYTES + 1)
    if len(content) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="Зображення перевищує 10 МБ.")
    try:
        with Image.open(BytesIO(content)) as image:
            if image.width * image.height > 20_000_000:
                raise HTTPException(
                    status_code=413,
                    detail="Розмір зображення перевищує ліміт 20 мегапікселів.",
                )
            return np.asarray(image.convert("RGB"))
    except (UnidentifiedImageError, OSError) as error:
        raise HTTPException(status_code=400, detail="Файл не є коректним зображенням.") from error


def _encode_image(image):
    if image is None:
        return None
    buffer = BytesIO()
    Image.fromarray(image).save(buffer, format="JPEG", quality=88)
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def _model_error(error):
    if isinstance(error, FileNotFoundError):
        return HTTPException(status_code=503, detail=str(error))
    if isinstance(error, ValueError):
        return HTTPException(status_code=400, detail=str(error))
    raise error


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/api/models")
def models():
    return [
        {
            "id": model_id,
            "name": label,
            "description": MODEL_DESCRIPTIONS[model_id],
        }
        for model_id, label in MODEL_IDS.items()
    ]


@app.post("/api/predict/{model_id}")
async def predict(model_id: str, file: UploadFile = File(...)):
    if model_id not in MODEL_IDS:
        raise HTTPException(status_code=404, detail="Модель не знайдено.")
    image = await read_rgb_image(file)
    started_at = time.perf_counter()
    try:
        annotated, message = predict_model(model_id, image)
    except (FileNotFoundError, ValueError) as error:
        raise _model_error(error) from error
    return {
        "model_id": model_id,
        "message": message,
        "annotated_image": _encode_image(annotated),
        "inference_time_ms": round((time.perf_counter() - started_at) * 1000, 1),
    }


@app.post("/api/recognize")
async def recognize(file: UploadFile = File(...)):
    image = await read_rgb_image(file)
    started_at = time.perf_counter()
    try:
        plate, confidence, annotated, message = recognize_plate(image)
    except (FileNotFoundError, ValueError) as error:
        raise _model_error(error) from error
    return {
        "plate_number": plate,
        "confidence": confidence,
        "message": message,
        "annotated_image": _encode_image(annotated),
        "inference_time_ms": round((time.perf_counter() - started_at) * 1000, 1),
    }
