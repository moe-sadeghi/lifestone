from flask import Flask, render_template, request, send_file, redirect, url_for, session
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image as ReportLabImage
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from werkzeug.utils import secure_filename
from image_processor import process_slab_image
from datetime import datetime
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import os
import json
import time
import logging

# Flask setup
app = Flask(__name__)
app.secret_key = "your-secret-key"  # Replace with a secure key for session management
UPLOAD_FOLDER = "static/uploads"
OUTPUT_FOLDER = "static/outputs"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["OUTPUT_FOLDER"] = OUTPUT_FOLDER

# Configure logging
logging.basicConfig(level=logging.DEBUG)
app.logger.setLevel(logging.DEBUG)

# Activity log file
ACTIVITY_LOG_FILE = "activity_log.json"

# Admin email for activity log
ADMIN_EMAIL = "myemail@gmail.com"  # Replace with your email address

# Allowed logo formats and size limit (1MB)
ALLOWED_LOGO_EXTENSIONS = {'.png', '.jpg', '.jpeg'}
MAX_LOGO_SIZE = 1 * 1024 * 1024  # 1MB in bytes

# Initialize activity log
def init_activity_log():
    if not os.path.exists(ACTIVITY_LOG_FILE):
        with open(ACTIVITY_LOG_FILE, 'w') as f:
            json.dump({"total_submissions": 0, "testers": {}}, f)

# Load activity log
def load_activity_log():
    init_activity_log()
    with open(ACTIVITY_LOG_FILE, 'r') as f:
        return json.load(f)

# Save activity log
def save_activity_log(log_data):
    with open(ACTIVITY_LOG_FILE, 'w') as f:
        json.dump(log_data, f, indent=4)

# Update activity log and send to admin if needed
def update_activity_log(tester_email, timestamp, serial_number):
    log_data = load_activity_log()
    if tester_email not in log_data["testers"]:
        log_data["testers"][tester_email] = {"count": 0, "submissions": []}
    log_data["testers"][tester_email]["count"] += 1
    log_data["testers"][tester_email]["submissions"].append({"timestamp": timestamp, "serial_number": serial_number})
    log_data["total_submissions"] += 1
    save_activity_log(log_data)

    # Send email to admin after every 5 submissions
    if log_data["total_submissions"] % 5 == 0:
        send_activity_log_to_admin(log_data)

# Send activity log to admin
def send_activity_log_to_admin(log_data):
    msg = MIMEMultipart()
    msg['From'] = os.getenv('SMTP_EMAIL', 'myemail@gmail.com')  # Replace with your SMTP email
    msg['To'] = ADMIN_EMAIL
    msg['Subject'] = "Activity Log Update - Stone Slab Documentation"

    # Format the log as a readable message
    log_text = "Activity Log:\n\n"
    log_text += f"Total Submissions: {log_data['total_submissions']}\n\n"
    for email, data in log_data["testers"].items():
        log_text += f"Tester Email: {email}\n"
        log_text += f"Number of Catalogs Created: {data['count']}\n"
        log_text += "Submissions:\n"
        for submission in data["submissions"]:
            log_text += f"  - Time: {submission['timestamp']}, Serial Number: {submission['serial_number']}\n"
        log_text += "\n"

    msg.attach(MIMEText(log_text, 'plain'))

    with smtplib.SMTP('smtp.gmail.com', 587) as server:
        server.starttls()
        server.login(os.getenv('SMTP_EMAIL', 'myemail@gmail.com'), os.getenv('SMTP_PASSWORD', 'your-app-password'))
        server.send_message(msg)

# Validate logo file
def allowed_logo_file(filename):
    return '.' in filename and os.path.splitext(filename)[1].lower() in ALLOWED_LOGO_EXTENSIONS

# PDF generation with ReportLab
def generate_pdf(serial_number, timestamp, data, output_image_path, support_images, company_logo_path=None, company_name=None, is_calibrated=True):
    pdf_path = os.path.join(app.config['OUTPUT_FOLDER'], f"report_{serial_number}_{timestamp}.pdf")
    doc = SimpleDocTemplate(pdf_path, pagesize=A4, rightMargin=20*mm, leftMargin=20*mm, topMargin=20*mm, bottomMargin=20*mm)
    
    # Define header and footer
    def add_header_footer(canvas, doc):
        canvas.saveState()
        # Footer
        canvas.setFont("Helvetica", 10)
        canvas.setFillColor(colors.grey)
        canvas.drawString(20*mm, 10*mm, "Powered by Lifestone")
        canvas.restoreState()

    elements = []

    # Styles
    styles = getSampleStyleSheet()
    title_style = styles['Heading1']
    title_style.alignment = 1  # Center
    subtitle_style = styles['Heading3']
    subtitle_style.alignment = 1
    normal_style = styles['Normal']
    normal_style.spaceAfter = 12
    warning_style = ParagraphStyle(name='WarningStyle', fontSize=8, textColor=colors.red, alignment=1)

    # Header with company logo and name (or placeholder)
    try:
        if company_logo_path and os.path.exists(company_logo_path):
            logo = ReportLabImage(company_logo_path, width=50*mm, height=50*mm)
            logo.hAlign = 'CENTER'
            elements.append(logo)
            elements.append(Spacer(1, 10*mm))
            app.logger.info(f"Successfully added logo to PDF: {company_logo_path}")
        else:
            # Placeholder: light gray box
            canvas_obj = canvas.Canvas(pdf_path)
            canvas_obj.setFillColor(colors.lightgrey)
            canvas_obj.rect(80*mm, 245*mm, 50*mm, 50*mm, fill=1)
            canvas_obj.save()
            elements.append(Spacer(1, 50*mm))
            app.logger.info("No logo provided; using light gray placeholder box.")
    except Exception as e:
        app.logger.error(f"Error adding logo to PDF: {str(e)}")
        # Fallback to placeholder
        canvas_obj = canvas.Canvas(pdf_path)
        canvas_obj.setFillColor(colors.lightgrey)
        canvas_obj.rect(80*mm, 245*mm, 50*mm, 50*mm, fill=1)
        canvas_obj.save()
        elements.append(Spacer(1, 50*mm))
        app.logger.info("Used placeholder box due to logo rendering error.")

    if company_name:
        elements.append(Paragraph(company_name, title_style))
        elements.append(Spacer(1, 10*mm))
    elements.append(Spacer(1, 20*mm))

    # Cover Page Content
    serial_number_text = serial_number if serial_number else "Not provided"
    material_text = data['material'] if data['material'] else "Not provided"
    elements.append(Paragraph(f"Slab Serial: {serial_number_text}", normal_style))
    elements.append(Paragraph(f"Material: {material_text}", normal_style))
    elements.append(Paragraph(f"Date: {datetime.now().strftime('%B %d, %Y')}", normal_style))
    elements.append(Spacer(1, 40*mm))

    # Page 2: Corrected Slab Image
    elements.append(Spacer(1, 0))  # Force new page
    elements.append(Paragraph("Slab Image", title_style))
    elements.append(Spacer(1, 10*mm))
    slab_image = ReportLabImage(output_image_path, width=160*mm, height=100*mm)
    slab_image.hAlign = 'CENTER'

    if not is_calibrated:
        # Add a red border with repetitive warning text around the image
        warning_text = "NOT CALIBRATED IMAGE - NO CORRECTION APPLIED"
        warning_box = Table([[slab_image]], colWidths=[160*mm], rowHeights=[100*mm])
        warning_box.setStyle(TableStyle([
            ('BOX', (0, 0), (-1, -1), 2, colors.red),
            ('TEXTCOLOR', (0, 0), (-1, -1), colors.red),
            ('FONTSIZE', (0, 0), (-1, -1), 8),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING', (0, 0), (-1, -1), 10),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
            ('LEFTPADDING', (0, 0), (-1, -1), 10),
            ('RIGHTPADDING', (0, 0), (-1, -1), 10),
        ]))
        # Add warning text around the image
        elements.append(Paragraph(warning_text, warning_style))
        elements.append(warning_box)
        elements.append(Paragraph(warning_text, warning_style))
    else:
        elements.append(slab_image)

    elements.append(Paragraph(f"{'Corrected' if is_calibrated else 'Uncorrected'} image of the slab ({serial_number_text}).", normal_style))

    # Page 3: Slab Specifications
    elements.append(Spacer(1, 0))  # Force new page
    elements.append(Paragraph("Slab Specifications", title_style))
    elements.append(Spacer(1, 10*mm))
    table_data = [
        ["Property", "Value"],
        ["Project Name", data['project_name'] if data['project_name'] else "Not provided"],
        ["Thickness", f"{data['thickness']:.1f} {data['unit']}"],
        ["Length", f"{data['length']} cm" if data['length'] else "Not provided"],
        ["Width", f"{data['width']} cm" if data['width'] else "Not provided"],
        ["Material", data['material'] if data['material'] else "Not provided"],
        ["Serial Number", serial_number if serial_number else "Not provided"],
        ["Make", data['make']],
        ["Model", data['model']],
        ["Batch/Lot Number", data['batch_number']],
    ]
    table = Table(table_data, colWidths=[50*mm, 100*mm])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 12),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.white),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
    ]))
    elements.append(table)

    # Page 4: Supporting Images and Notes (if provided)
    if support_images:
        elements.append(Spacer(1, 0))  # Force new page
        elements.append(Paragraph("Supporting Documentation", title_style))
        elements.append(Spacer(1, 10*mm))
        for index, (image_path, notes) in enumerate(support_images):
            if os.path.exists(image_path):
                caption = f"Supporting Image {index + 1}"
                elements.append(Paragraph(caption, subtitle_style))
                elements.append(Spacer(1, 5*mm))
                img = ReportLabImage(image_path, width=120*mm, height=80*mm)
                img.hAlign = 'CENTER'
                elements.append(img)
                notes_text = notes if notes else "No notes provided."
                elements.append(Paragraph(f"Notes: {notes_text}", normal_style))
                elements.append(Spacer(1, 10*mm))
            else:
                app.logger.error(f"Supporting image not found: {image_path}")

    # Page 5: Notes
    elements.append(Spacer(1, 0))  # Force new page
    elements.append(Paragraph("Notes", title_style))
    elements.append(Spacer(1, 10*mm))
    notes = data['notes'] if data['notes'] else "No notes provided."
    for line in notes.split('\n'):
        if line.strip():
            elements.append(Paragraph(f"• {line}", normal_style))

    # Build PDF with header and footer
    doc.build(elements, onFirstPage=add_header_footer, onLaterPages=add_header_footer)
    return pdf_path

# Routes
@app.route("/")
def index():
    # Initialize slab count in session if not present
    if 'slab_count' not in session:
        session['slab_count'] = 0
    # Clear any continue_as_is flag on new form load
    session.pop('continue_as_is', None)
    session.pop('slab_image_path', None)
    return render_template("index.html")

@app.route("/confirm", methods=["POST"])
def confirm():
    # Validate mandatory form fields
    required_fields = ['slab_image', 'thickness', 'tester_email', 'terms']
    for field in required_fields:
        if field not in request.form and field not in request.files:
            return f"""
            <div class="error-box">
                <h4>Missing Required Field</h4>
                <p>The field '{field}' is required but was not provided.</p>
                <p>Please fill in all required fields and try again.</p>
                <p><a href="/">Go Back</a></p>
            </div>
            """, 400

    # Collect form data
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    thickness = float(request.form.get('thickness'))
    unit = request.form.get('unit', 'mm')
    if unit == 'inch':
        thickness *= 25.4  # Convert to mm
    data = {
        'thickness': thickness,
        'unit': unit,
        'project_name': request.form.get('project_name', ''),
        'length': request.form.get('length', ''),
        'width': request.form.get('width', ''),
        'material': request.form.get('material', ''),
        'serial_number': request.form.get('serial_number', ''),
        'make': request.form.get('make', 'N/A'),
        'model': request.form.get('model', 'N/A'),
        'batch_number': request.form.get('batch_number', 'N/A'),
        'tester_email': request.form.get('tester_email'),
        'notes': request.form.get('notes', '')
    }

    # Handle company logo and name
    company_name = request.form.get('company_name', '')
    company_logo_path = None
    if 'company_logo' in request.files:
        logo = request.files['company_logo']
        if logo and logo.filename:
            # Validate logo file
            if not allowed_logo_file(logo.filename):
                return """
                <div class="error-box">
                    <h4>Invalid Logo File</h4>
                    <p>The uploaded logo file must be a PNG or JPG/JPEG image.</p>
                    <p>Please upload a valid image and try again.</p>
                    <p><a href="/">Go Back</a></p>
                </div>
                """, 400

            # Check file size
            logo.seek(0, os.SEEK_END)
            file_size = logo.tell()
            logo.seek(0)
            if file_size > MAX_LOGO_SIZE:
                return """
                <div class="error-box">
                    <h4>Logo File Too Large</h4>
                    <p>The uploaded logo file exceeds the maximum size of 1MB.</p>
                    <p>Please upload a smaller image and try again.</p>
                    <p><a href="/">Go Back</a></p>
                </div>
                """, 400

            # Save the logo file
            try:
                filename = secure_filename(f"logo_{timestamp}_{logo.filename}")
                logo_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                logo.save(logo_path)
                if os.path.exists(logo_path):
                    company_logo_path = logo_path
                    app.logger.info(f"Logo saved successfully: {logo_path}")
                else:
                    app.logger.error(f"Failed to save logo: {logo_path}")
            except Exception as e:
                app.logger.error(f"Error saving logo: {str(e)}")
                company_logo_path = None

    # Save uploaded files
    file_mappings = {}
    support_images = []
    for file_key in ['slab_image']:
        file = request.files.get(file_key)
        if file and file.filename:
            filename = secure_filename(f"{file_key}_{timestamp}_{file.filename}")
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(file_path)
            file_mappings[file_key] = file_path

    # Handle supporting images and their notes dynamically
    index = 0
    while True:
        image_key = f"support_image_{index}"
        notes_key = f"support_notes_{index}"
        if image_key not in request.files:
            break
        file = request.files[image_key]
        notes = request.form.get(notes_key, '')
        if file and file.filename:
            filename = secure_filename(f"support_{index}_{timestamp}_{file.filename}")
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(file_path)
            support_images.append((file_path, notes))
        index += 1

    if 'slab_image' not in file_mappings:
        return """
        <div class="error-box">
            <h4>No Slab Image Uploaded</h4>
            <p>We couldn't find the main slab image in your submission.</p>
            <p>Please upload the main slab image and try again.</p>
            <p><a href="/">Go Back</a></p>
        </div>
        """, 400

    # Process slab image (sanitize serial number in filename)
    sanitized_serial_number = data['serial_number'].replace(" ", "_") if data['serial_number'] else "unknown"
    output_image_path = os.path.join(app.config['OUTPUT_FOLDER'], f"processed_{sanitized_serial_number}_{timestamp}.jpg")

    # Check if user chose to continue without calibration
    continue_as_is = session.get('continue_as_is', False)
    is_calibrated = True

    if continue_as_is:
        # Use the previously saved slab image path
        input_image_path = session.get('slab_image_path')
        if not input_image_path or not os.path.exists(input_image_path):
            return """
            <div class="error-box">
                <h4>Image Not Found</h4>
                <p>The original image could not be found. Please try uploading again.</p>
                <p><a href="/">Go Back</a></p>
            </div>
            """, 400
        # Copy the original image to the output path without processing
        try:
            with open(input_image_path, 'rb') as src, open(output_image_path, 'wb') as dst:
                dst.write(src.read())
            is_calibrated = False
            app.logger.info(f"Image passed as is without calibration: {output_image_path}")
        except Exception as e:
            app.logger.error(f"Error copying uncalibrated image: {str(e)}")
            return f"""
            <div class="error-box">
                <h4>Error Processing Image</h4>
                <p>Failed to process the image as is: {str(e)}</p>
                <p>Please try again or contact support at info@lifestone.ca.</p>
                <p><a href="/">Go Back</a></p>
            </div>
            """, 500
    else:
        # Attempt to process the image with QR code detection
        try:
            process_slab_image(
                input_path=file_mappings['slab_image'],
                output_path=output_image_path,
                stone_thickness_mm=thickness
            )
            is_calibrated = True
        except ValueError as e:
            # Enhanced error feedback for missing markers with option to continue
            if "No ArUco markers detected" in str(e) or "Missing marker IDs" in str(e):
                # Store the slab image path and continue_as_is flag in session
                session['continue_as_is'] = True
                session['slab_image_path'] = file_mappings['slab_image']
                return """
                <div class="error-box">
                    <h4>QR Code Detection Failed</h4>
                    <p>We couldn’t find the QR codes in your image. This might be due to:</p>
                    <ul>
                        <li>Missing markers in one or more corners of the image.</li>
                        <li>Poor lighting conditions affecting marker visibility.</li>
                        <li>The image being taken from an angle that obscures the markers.</li>
                    </ul>
                    <p><strong>What to do:</strong></p>
                    <p>- Ensure all four corners of the slab have visible QR codes (IDs 1, 18, 43, 14).</p>
                    <p>- Take the photo in good lighting, preferably with even illumination.</p>
                    <p>- Position the camera directly above the slab for a clear, straight-on view.</p>
                    <p><strong>Alternatively:</strong></p>
                    <p>You can continue without calibration. Note that no correction or calibration will be applied to the image, and it will be used as is.</p>
                    <div class="options">
                        <a href="/">Go Back and Try Again</a>
                        <form action="/confirm" method="POST" style="display: inline;">
                            {% for key, value in request.form.items() %}
                                {% if key != 'slab_image' %}
                                    <input type="hidden" name="{{ key }}" value="{{ value }}">
                                {% endif %}
                            {% endfor %}
                            <button type="submit">Continue as Is</button>
                        </form>
                    </div>
                </div>
                """, 400
            return f"""
            <div class="error-box">
                <h4>Image Processing Error</h4>
                <p>An error occurred while processing your image: {str(e)}</p>
                <p>Please try again or contact support if the issue persists.</p>
                <p><a href="/">Go Back</a></p>
            </div>
            """, 500
        except Exception as e:
            return f"""
            <div class="error-box">
                <h4>Unexpected Error</h4>
                <p>An unexpected error occurred while processing your image: {str(e)}</p>
                <p>Please try again or contact support at info@lifestone.ca.</p>
                <p><a href="/">Go Back</a></p>
            </div>
            """, 500

    # Generate PDF with ReportLab
    pdf_path = generate_pdf(sanitized_serial_number, timestamp, data, output_image_path, support_images, company_logo_path, company_name, is_calibrated)
    app.logger.info(f"Generated PDF: {pdf_path}, exists: {os.path.exists(pdf_path)}")

    # Ensure files exist before proceeding
    max_attempts = 5
    attempt = 0
    while attempt < max_attempts:
        if os.path.exists(pdf_path) and os.path.exists(output_image_path):
            break
        app.logger.info(f"Files not ready: PDF {pdf_path} exists: {os.path.exists(pdf_path)}, Image {output_image_path} exists: {os.path.exists(output_image_path)}, retrying... (attempt {attempt + 1}/{max_attempts})")
        time.sleep(1)  # Wait 1 second before retrying
        attempt += 1

    if not os.path.exists(pdf_path) or not os.path.exists(output_image_path):
        app.logger.error(f"Files not found after retries: PDF {pdf_path} exists: {os.path.exists(pdf_path)}, Image {output_image_path} exists: {os.path.exists(output_image_path)}")
        return """
        <div class="error-box">
            <h4>File Generation Failed</h4>
            <p>We couldn’t generate the report files. This might be due to a server issue.</p>
            <p>Please try again later or contact support at info@lifestone.ca.</p>
            <p><a href="/">Go Back</a></p>
        </div>
        """, 500

    # Log the activity only if image processing succeeds or user chooses to continue
    update_activity_log(data['tester_email'], timestamp, sanitized_serial_number)

    # Increment session slab counter
    session['slab_count'] = session.get('slab_count', 0) + 1

    # Clear session flags
    session.pop('continue_as_is', None)
    session.pop('slab_image_path', None)

    # Prepare results for local downloads
    results = {'downloads': [os.path.basename(pdf_path), os.path.basename(output_image_path)]}
    app.logger.info(f"Download paths: {results['downloads']}")

    # Render confirmation page with both results and data
    return render_template('confirm.html', results=results, data=data)

# Route to reset the session slab count
@app.route("/reset_count", methods=["POST"])
def reset_count():
    session['slab_count'] = 0
    return redirect(url_for('index'))

# Route to serve files
@app.route('/files/<filename>')
def serve_file(filename):
    try:
        file_path = os.path.join(app.config['OUTPUT_FOLDER'], filename)
        # Retry mechanism to ensure file exists
        max_attempts = 5
        attempt = 0
        while attempt < max_attempts:
            if os.path.exists(file_path):
                break
            app.logger.info(f"File {file_path} not found, retrying... (attempt {attempt + 1}/{max_attempts})")
            time.sleep(1)  # Wait 1 second before retrying
            attempt += 1
        
        if not os.path.exists(file_path):
            app.logger.error(f"File not found after retries: {file_path}")
            return f"""
            <div class="error-box">
                <h4>File Not Found</h4>
                <p>The file '{filename}' could not be found on the server.</p>
                <p>Please try generating the report again or contact support.</p>
                <p><a href="/">Go Back</a></p>
            </div>
            """, 404

        # Determine the correct MIME type based on file extension
        if filename.endswith('.pdf'):
            mimetype = 'application/pdf'
        elif filename.endswith('.jpg') or filename.endswith('.jpeg'):
            mimetype = 'image/jpeg'
        else:
            mimetype = 'application/octet-stream'
        
        # Create response with Content-Disposition header
        response = send_file(
            file_path,
            as_attachment=True,
            download_name=filename,
            mimetype=mimetype
        )
        response.headers['Content-Disposition'] = f'attachment; filename="{filename}"'
        app.logger.info(f"Serving file: {file_path}, MIME type: {mimetype}, Content-Disposition: {response.headers['Content-Disposition']}")
        return response
    except Exception as e:
        app.logger.error(f"Error serving file {filename}: {str(e)}")
        return f"""
        <div class="error-box">
            <h4>Error Downloading File</h4>
            <p>An error occurred while downloading the file: {str(e)}</p>
            <p>Please try again or contact support at info@lifestone.ca.</p>
            <p><a href="/">Go Back</a></p>
        </div>
        """, 500

if __name__ == "__main__":
    import waitress
    print("Starting Waitress server...")
    waitress.serve(app, host="0.0.0.0", port=5000)