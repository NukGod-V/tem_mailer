# routes/tracking.py
from flask import Blueprint, send_file, request
from models import db, EmailStatus
from datetime import datetime, timezone
from utils.logger import logger

track_bp = Blueprint('track', __name__)

# List of known proxy indicators
PROXY_USER_AGENTS = [
    "GoogleImageProxy", "Google-Apps-Script", "Google", "Apple", "Outlook",
    "Thunderbird", "iCloud", "Microsoft", "Yahoo", "Yandex", "bot"
]

def is_proxy_user_agent(user_agent):
    return any(proxy.lower() in user_agent.lower() for proxy in PROXY_USER_AGENTS)

@track_bp.route('/track/<tracking_id>.png')
def track_open(tracking_id):
    print(f"[TRACKING] Email opened with ID: {tracking_id}")
    client_ip = request.remote_addr
    user_agent = request.headers.get('User-Agent', 'Unknown')

    logger.info(f"Tracking pixel accessed for ID: {tracking_id}")
    logger.debug(f"Request from IP: {client_ip}, User-Agent: {user_agent}")

    log = EmailStatus.query.filter_by(tracking_id=tracking_id).first()

    if log:
        if not log.opened:
            if is_proxy_user_agent(user_agent):
                logger.info(f"Tracking pixel triggered by proxy (not marked as opened). UA: {user_agent}")
            else:
                logger.info(f"First real open detected for email from {log.from_email} to {log.to_email}")
                log.opened = True
                log.opened_at = datetime.now(timezone.utc)
                try:
                    db.session.commit()
                    logger.info(f"Email tracking status updated successfully for ID: {tracking_id}")
                except Exception as e:
                    db.session.rollback()
                    logger.error(f"Failed to update email tracking status: {str(e)}", exc_info=True)
        else:
            logger.info(f"Repeat open detected for email with tracking ID: {tracking_id}")
            logger.debug(f"Previous open at: {log.opened_at}")
    else:
        logger.warning(f"No email record found for tracking ID: {tracking_id}")

    response = send_file('tracking_pixels/pixel.png', mimetype='image/png')
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response