import os
from pathlib import Path

import gradio as gr

from model_inference import (
    MODEL_DESCRIPTIONS,
    MODEL_IDS,
    analyze_vehicle_and_space,
    predict_model,
)


ROOT = Path(__file__).resolve().parent
TRAINING_PLOT_DIR = ROOT / "data" / "models" / "training_plots"
MODEL_CHOICES = list(MODEL_IDS.values())
MODEL_LABEL_TO_ID = {label: model_id for model_id, label in MODEL_IDS.items()}
MODEL_PLOTS = {
    "lpr_detector": "lpr_training.png",
    "character_recognition": "ocr_training.png",
    "parking_occupancy": "pklot_training.png",
}


def get_model_details(model_label):
    model_id = MODEL_LABEL_TO_ID.get(model_label)
    if model_id is None:
        raise gr.Error("Select a model from the list.")
    plot_path = TRAINING_PLOT_DIR / MODEL_PLOTS[model_id]
    if plot_path.is_file():
        return (
            MODEL_DESCRIPTIONS[model_id],
            str(plot_path),
            f"Training curves for {model_label}.",
        )
    return (
        MODEL_DESCRIPTIONS[model_id],
        None,
        "Training curves are not available yet. Run the corresponding notebook training cell.",
    )


DEFAULT_MODEL_DESCRIPTION, DEFAULT_TRAINING_PLOT, DEFAULT_TRAINING_PLOT_STATUS = (
    get_model_details(MODEL_CHOICES[0])
)


def run_model(model_label, rgb_image):
    model_id = MODEL_LABEL_TO_ID.get(model_label)
    if model_id is None:
        raise gr.Error("Select a model from the list.")
    if rgb_image is None:
        raise gr.Error("Upload an image to run the selected model.")
    try:
        return predict_model(model_id, rgb_image)
    except (FileNotFoundError, ValueError) as error:
        raise gr.Error(str(error)) from error


def run_full_analysis(vehicle_image, parking_space_image):
    if vehicle_image is None:
        raise gr.Error("Upload a vehicle photo to detect and read its license plate.")
    if parking_space_image is None:
        raise gr.Error("Upload a separate photo of one parking space.")
    try:
        return analyze_vehicle_and_space(vehicle_image, parking_space_image)
    except (FileNotFoundError, ValueError) as error:
        raise gr.Error(str(error)) from error


CSS = """
.gradio-container {max-width: 1120px !important; margin: 0 auto !important;}
.pv-hero {padding: 28px 30px; border-radius: 20px; background: linear-gradient(120deg, #102b46, #164f59); color: #f3f8fa;}
.pv-hero h1 {margin: 0 0 8px; font-size: 32px;}
.pv-hero p {margin: 0; color: #c8dce2; font-size: 16px;}
.pv-panel {border: 1px solid #dce5e9; border-radius: 16px; padding: 18px;}
"""

with gr.Blocks(title="ParkVision - AI Model Lab") as demo:
    gr.HTML(
        """
        <div class="pv-hero">
          <h1>ParkVision - AI Model Lab</h1>
          <p>Run license-plate detection, OCR, and parking-space occupancy from one screen.</p>
        </div>
        """
    )
    with gr.Group(elem_classes=["pv-panel"]):
        gr.Markdown("## Complete analysis")
        gr.Markdown(
            "Upload a vehicle photo and a separate close-up of one parking space. "
            "One action runs plate detection, OCR, and parking-space classification."
        )
        with gr.Row():
            vehicle_image_input = gr.Image(
                type="numpy",
                sources=["upload"],
                label="Vehicle photo (plate detection and OCR)",
            )
            parking_space_input = gr.Image(
                type="numpy",
                sources=["upload"],
                label="One parking space (occupancy)",
            )
        analyze_button = gr.Button("Analyze both images", variant="primary")
        with gr.Row():
            vehicle_result_image = gr.Image(label="Vehicle with detected plate")
            plate_result_text = gr.Textbox(
                label="License plate and OCR",
                lines=3,
                interactive=False,
                placeholder="The plate detection and OCR result will appear here.",
            )
            occupancy_result_text = gr.Textbox(
                label="Parking-space occupancy",
                lines=3,
                interactive=False,
                placeholder="The parking-space classification will appear here.",
            )
        analyze_button.click(
            run_full_analysis,
            inputs=[vehicle_image_input, parking_space_input],
            outputs=[vehicle_result_image, plate_result_text, occupancy_result_text],
        )

    with gr.Accordion("Test one model individually", open=False):
        with gr.Row():
            with gr.Column(scale=1, elem_classes=["pv-panel"]):
                model_input = gr.Dropdown(
                    choices=MODEL_CHOICES,
                    value=MODEL_CHOICES[0],
                    label="Trained model",
                )
                model_description = gr.Markdown(DEFAULT_MODEL_DESCRIPTION)
                image_input = gr.Image(
                    type="numpy",
                    sources=["upload"],
                    label="Image to analyze",
                )
                run_button = gr.Button("Run model", variant="primary")
            with gr.Column(scale=1, elem_classes=["pv-panel"]):
                result_image = gr.Image(label="Prediction")
                result_text = gr.Textbox(
                    label="Model result",
                    lines=3,
                    interactive=False,
                    placeholder="The prediction will appear here.",
                )
                training_plot = gr.Image(
                    label="Training curves",
                    value=DEFAULT_TRAINING_PLOT,
                    interactive=False,
                )
                training_plot_status = gr.Markdown(DEFAULT_TRAINING_PLOT_STATUS)
                gr.Markdown(
                    "Models run locally from `data/models/`. Uploaded images are not sent "
                    "to external services."
                )

    model_input.change(
        get_model_details,
        inputs=model_input,
        outputs=[model_description, training_plot, training_plot_status],
    )
    run_button.click(
        run_model,
        inputs=[model_input, image_input],
        outputs=[result_image, result_text],
    )


if __name__ == "__main__":
    demo.queue().launch(
        server_name=os.environ.get("HOST", "127.0.0.1"),
        server_port=int(os.environ.get("PORT", "7860")),
        share=False,
        show_error=True,
        css=CSS,
    )
