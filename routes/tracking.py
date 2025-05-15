from flask import Blueprint, send_file, request
from models import db, EmailStatus
from datetime import datetime
from utils.logger import logger
import pytz

track_bp = Blueprint('track', __name__)

@track_bp.route('/track/<tracking_id>.png')
def track_open(tracking_id):
    print(f"[TRACKING] Email opened with ID: {tracking_id}")
    client_ip = request.remote_addr
    user_agent = request.headers.get('User-Agent', 'Unknown')

    logger.info(f"Tracking pixel accessed for ID: {tracking_id}")
    logger.debug(f"Request from IP: {client_ip}, User-Agent: {user_agent}")

    log = EmailStatus.query.filter_by(tracking_id=tracking_id).first()

    if log:
        log.view_count = (log.view_count or 0) + 1

        if not log.opened and log.view_count >= 2:
            ist = pytz.timezone('Asia/Kolkata')
            log.opened = True
            log.opened_at = datetime.now(ist)
            logger.info(f"Confirmed real open (2nd+ view) for email from {log.from_email} to {log.to_email}")

        try:
            db.session.commit()
            logger.debug(f"Email status updated for tracking ID: {tracking_id}")
        except Exception as e:
            db.session.rollback()
            logger.error(f"Failed to update email tracking status: {str(e)}", exc_info=True)
    else:
        logger.warning(f"No email record found for tracking ID: {tracking_id}")

    response = send_file('tracking_pixels/pixel.png', mimetype='image/png')
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response
