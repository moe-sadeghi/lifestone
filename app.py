from flask import Flask, render_template, request, send_file, redirect, url_for
import os
from werkzeug.utils import secure_filename
from image_processor import process_slab_image

app = Flask(__name__)
UPLOAD_FOLDER = 'static'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/confirm', methods=['POST'])
def confirm():
    file = request.files['image']
    if not file or file.filename == '':
        return "No image uploaded", 400

    thickness = request.form.get('thickness', '30')
    notes = request.form.get('notes', '')
    terms = request.form.get('terms')

    if not terms:
        return "You must accept the terms and conditions.", 400

    filename = secure_filename(file.filename)
    input_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    output_path = os.path.join(app.config['UPLOAD_FOLDER'], 'processed.jpg')

    file.save(input_path)

    try:
        process_slab_image(
            input_path=input_path,
            output_path=output_path,
            stone_thickness_mm=float(thickness)
        )
    except Exception as e:
        return f"Processing failed: {str(e)}", 500

    return send_file(output_path, as_attachment=True, download_name="corrected_slab.jpg")

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
    