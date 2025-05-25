# routes/email.py
from flask import Blueprint, request, jsonify
from utils.email_sender import send_bulk_emails
from utils.logger import logger
from werkzeug.utils import secure_filename
from datetime import datetime
from models import ScheduledEmail,GmailAccount,User
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
    if request.is_json:    
        data = request.get_json()
    else:
        data = request.form.to_dict()
    # Check for file
    file = request.files.get('attachment')
    filepath = None

    if file:
        filename = secure_filename(file.filename)
        logger.info(f"Attachment received: {filename}")
        
        if not is_file_safe(filename):
            logger.warning(f"Disallowed file type rejected: {filename}")
            return jsonify({"error": "Disallowed file type"}), 400

        #Make sure file is present
        os.makedirs(UPLOAD_FOLDER, exist_ok=True)

        filepath = os.path.join(UPLOAD_FOLDER, filename)
        file.save(filepath)
        logger.info(f"File saved at: {filepath}")
    else:
        logger.info("No attachment received with request")
    
    # Token validation
    from_role = data.get('from_role')
    token = data.get('token')

    logger.info(f"API accessed with token: {token[:4]}...{token[-4:] if token and len(token) > 8 else ''}")

    # Validate 'from_role' exists in gmail_accounts
    gmail_account = GmailAccount.query.filter_by(role=from_role).first()
    if not gmail_account:
        logger.warning(f"Invalid from_role: {from_role}")
        return jsonify({"error": f"Invalid sender role '{from_role}'"}), 400

    # Validate 'token' exists for a user matching 'from_role' and is active
    user = User.query.filter_by(api_token=token, service_name=from_role, is_active=True).first()
    if not user:
        logger.warning(f"Unauthorized token attempt for role '{from_role}': {token[:4]}...")
        return jsonify({"error": "Invalid or inactive token for the specified role"}), 401

    logger.info(f"Authenticated user: {user.service_name} (ID: {user.user_id})")

    # Extract email info
    to_raw = data.get("to", [])
    try:
        to = json.loads(to_raw) if isinstance(to_raw, str) else to_raw
        logger.debug(f"Recipients parsed: {to}")
    except Exception as e:
        logger.error(f"Failed to parse recipients JSON: {str(e)}")
        return jsonify({"error": "Invalid JSON in 'to' field"}), 400
        
    subject = data.get('subject')
    template_name = data.get('template')
        
    body = data.get('body')

    scheduled_at_raw = data.get('scheduled_at')
    scheduled_at = None
    ist = pytz.timezone('Asia/Kolkata')
    if scheduled_at_raw and scheduled_at_raw.strip():
        try:
            scheduled_at = datetime.strptime(scheduled_at_raw.strip(), "%Y-%m-%d %H:%M:%S")
            scheduled_at = ist.localize(scheduled_at)
            print(scheduled_at)
            logger.info(f"Email scheduled for: {scheduled_at}")
        except ValueError:
            logger.warning("Invalid datetime format for 'scheduled_at'")
            return jsonify({"error": "Invalid 'scheduled_at' format. Use YYYY-MM-DD HH:MM:SS"}), 400
    else:
        logger.info("No scheduled_at provided; email will be sent immediately.")

    # Validate required fields
    if not from_role or not to or not subject:
        missing = []
        # if not from_role: missing.append("from_role")
        if not to: missing.append("to")
        if not subject: missing.append("subject")
        logger.warning(f"Missing required fields: {', '.join(missing)}")
        return jsonify({"error": f"Missing required fields: {', '.join(missing)}"}), 400

    content_type="text/html"
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

            success, failed_list = send_bulk_emails(from_role, to, subject, body, content_type, attachments,template_name)

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
                    body=body or "[NO BODY]",
                    content_type=content_type,
                    attachments=','.join(attachments) if attachments else None,
                    scheduled_at=scheduled_at,
                    template_name=template_name
                )
                db.session.add(scheduled)

            db.session.commit()
            return jsonify({"message": "Emails scheduled successfully."}), 200

    except Exception as e:
        logger.error(f"Email sending crashed with error: {str(e)}", exc_info=True)
        return jsonify({"error": str(e)}), 500