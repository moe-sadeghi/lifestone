from flask import Flask, render_template, request, send_file
import os
from werkzeug.utils import secure_filename
from image_processor import process_slab_image

# --------------------------------------------------
# Flask setup
# --------------------------------------------------
app = Flask(__name__)

UPLOAD_FOLDER = "static"           # all uploads + outputs
os.makedirs(UPLOAD_FOLDER, exist_ok=True)  # <‑‑ NEW: ensure it exists
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER


# --------------------------------------------------
# Routes
# --------------------------------------------------
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/confirm", methods=["POST"])
def confirm():
    # ---------- 1. Validate upload ----------
    file = request.files.get("image")
    if not file or file.filename == "":
        return "No image uploaded.", 400

    # ---------- 2. Validate form fields ----------
    thickness = request.form.get("thickness")
    if not thickness:
        return "Stone thickness is missing.", 400

    if "terms" not in request.form:
        return "You must accept the terms and conditions.", 400

    notes = request.form.get("notes", "")

    # ---------- 3. Save original ----------
    filename = secure_filename(file.filename)
    input_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
    file.save(input_path)

    # ---------- 4. Process ----------
    output_path = os.path.join(app.config["UPLOAD_FOLDER"], "processed.jpg")
    try:
        process_slab_image(
            input_path=input_path,
            output_path=output_path,
            stone_thickness_mm=float(thickness)
        )
    except Exception as e:
        # return full error text for easier debugging
        return f"Processing failed: {e}", 500

    # ---------- 5. Send file ----------
    return send_file(output_path,
                     as_attachment=True,
                     download_name="corrected_slab.jpg")


# --------------------------------------------------
# Dev entry‑point
# --------------------------------------------------
if __name__ == "__main__":
    # host 0.0.0.0 so it also works inside containers
    app.run(host="0.0.0.0", port=5000, debug=True)
