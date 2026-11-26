FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends libglib2.0-0 libgl1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN python -m pip install --upgrade pip \
    && python -m pip install -r requirements.txt

COPY manage.py main.py ai_api.py model_inference.py ./
COPY parking_project ./parking_project
COPY parking ./parking
COPY templates ./templates
COPY static ./static
COPY data/models/lpr_detector.pt ./data/models/lpr_detector.pt
COPY data/models/pklot_occupancy.keras ./data/models/pklot_occupancy.keras
COPY data/models/ukrainian_lp_sequence_model.keras ./data/models/ukrainian_lp_sequence_model.keras
COPY data/models/ukrainian_lp_characters.json ./data/models/ukrainian_lp_characters.json
COPY data/models/training_plots ./data/models/training_plots

EXPOSE 8000 8001 7860

CMD ["gunicorn", "parking_project.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "2"]
