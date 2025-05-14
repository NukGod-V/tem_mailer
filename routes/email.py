# routes/email.py
from flask import Blueprint, request, jsonify
from models import User
from utils.email_sender import send_bulk_emails
from utils.logger import logger
from werkzeug.utils import secure_filename
from datetime import datetime
from models import ScheduledEmail
import os
import json
import pytz

ALLOWED_EXTENSIONS = {'pdf', 'jpg', 'jpeg', 'png', 'docx', 'xlsx', 'txt'}
DISALLOWED_EXTENSIONS = {'exe', 'bat', 'sh'}
UPLOAD_FOLDER = 'attachments/'

def is_file_safe(filename):
    ext = filename.rsplit('.', 1)[-1].lower()
    return ext in ALLOWED_EXTENSIONS and ext not in DISALLOWED_EXTENSIONS

email_bp = Blueprint('email', __name__, url_prefix='/api')

@email_bp.route('/send_email', methods=['POST'])
def send_email():
    logger.info("Email API endpoint accessed")
    
    # Check for file
    file = request.files.get('attachment')
    filepath = None

    if file:
        filename = secure_filename(file.filename)
        logger.info(f"Attachment received: {filename}")
        
        if not is_file_safe(filename):
            logger.warning(f"Disallowed file type rejected: {filename}")
            return jsonify({"error": "Disallowed file type"}), 400

        filepath = os.path.join(UPLOAD_FOLDER, filename)
        file.save(filepath)
        logger.info(f"File saved at: {filepath}")
    else:
        logger.info("No attachment received with request")
        
    # data = request.get_json()
    data = request.form.to_dict()
    logger.debug(f"Request data: {data}")
    
    # Token validation
    token = data.get('token')
    logger.info(f"API accessed with token: {token[:4]}...{token[-4:] if token and len(token) > 8 else ''}")
    if not token:
        logger.warning("Missing token in request")
        return jsonify({"error": "Token missing"}), 400

    user = User.query.filter_by(api_token=token, is_active=True).first()
    if not user:
        logger.warning(f"Invalid token attempt: {token[:4]}...")
        return jsonify({"error": "Invalid or inactive token"}), 401
    
    logger.info(f"Authenticated user: {user.service_name} (ID: {user.user_id})")

    # Extract email info
    from_role = data.get('from_role')
    to_raw = data.get("to", [])
    try:
        to = json.loads(to_raw) if isinstance(to_raw, str) else to_raw
        logger.debug(f"Recipients parsed: {to}")
    except Exception as e:
        logger.error(f"Failed to parse recipients JSON: {str(e)}")
        return jsonify({"error": "Invalid JSON in 'to' field"}), 400
        
    subject = data.get('subject')
    template_name = data.get('template')
    variables_raw = data.get('variables', {})
    
    try:
        variables = json.loads(variables_raw) if isinstance(variables_raw, str) else variables_raw
        logger.debug(f"Template variables parsed: {variables}")
    except Exception as e:
        logger.error(f"Failed to parse variables JSON: {str(e)}")
        return jsonify({"error": "Invalid JSON in 'variables' field"}), 400
        
    body = data.get('body')

    scheduled_at_raw = data.get('scheduled_at')
    scheduled_at = None
    ist = pytz.timezone('Asia/Kolkata')
    
    if scheduled_at_raw:
        try:
            scheduled_at = datetime.strptime(scheduled_at_raw, "%Y-%m-%d %H:%M:%S")
            scheduled_at = ist.localize(scheduled_at)
            logger.info(f"Email scheduled for: {scheduled_at}")
        except ValueError:
            logger.warning("Invalid datetime format for 'scheduled_at'")
            return jsonify({"error": "Invalid 'scheduled_at' format. Use YYYY-MM-DD HH:MM:SS"}), 400

    # Validate required fields
    if not from_role or not to or not subject:
        missing = []
        if not from_role: missing.append("from_role")
        if not to: missing.append("to")
        if not subject: missing.append("subject")
        logger.warning(f"Missing required fields: {', '.join(missing)}")
        return jsonify({"error": f"Missing required fields: {', '.join(missing)}"}), 400

    # If template is used, render the body
    if template_name:
        try:
            logger.info(f"Using template: {template_name}")
            from utils.template_loader import load_and_render_template
            body = load_and_render_template(template_name, variables)
            content_type = "text/html"
        except FileNotFoundError as e:
            logger.error(f"Template not found: {template_name}, error: {str(e)}")
            return jsonify({"error": str(e)}), 404
    else:
        if not body:
            logger.warning("Missing body or template")
            return jsonify({"error": "Missing body or template"}), 400
        content_type = "text/html"  # Or switch to text/plain if needed
        logger.info("Using directly provided email body")

    # Send emails
    try:
        # Handle attachments
        attachments = [filepath] if filepath else []
        if attachments:
            logger.info(f"Including {len(attachments)} attachment(s)")
            
        recipient_count = len(to)
        if not scheduled_at:
            # Send immediately
            logger.info(f"Sending email: from_role={from_role}, to={recipient_count} recipient(s), subject='{subject}'")

            success, failed_list = send_bulk_emails(from_role, to, subject, body, content_type, attachments)

            if success:
                logger.info(f"All {recipient_count} emails sent successfully")
                return jsonify({"message": "Emails sent successfully."}), 200
            else:
                failed_count = len(failed_list)
                logger.warning(f"{failed_count} out of {recipient_count} emails failed to send")
                return jsonify({
                    "message": "Some emails failed to send.",
                    "failed_recipients": failed_list
                }), 400
        else:
            # Schedule email for later
            from models import db
            logger.info(f"Storing {recipient_count} emails to be sent at {scheduled_at}")
            for recipient in to:
                scheduled = ScheduledEmail(
                    from_email=from_role,  # resolve actual email in scheduler
                    to_email=recipient,
                    subject=subject,
                    body=body,
                    content_type=content_type,
                    attachments=','.join(attachments) if attachments else None,
                    scheduled_at=scheduled_at
                )
                db.session.add(scheduled)

            db.session.commit()
            return jsonify({"message": "Emails scheduled successfully."}), 200

    except Exception as e:
        logger.error(f"Email sending crashed with error: {str(e)}", exc_info=True)
        return jsonify({"error": str(e)}), 500