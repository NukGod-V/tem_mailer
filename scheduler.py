# scheduler.py
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime 
from models import ScheduledEmail, db
from utils.email_sender import send_bulk_emails
import pytz
from utils.logger import logger

def send_scheduled_emails(app):
    with app.app_context():
        ist = pytz.timezone('Asia/Kolkata')
        now = datetime.now(ist)
        pending_emails = ScheduledEmail.query.filter(
            ScheduledEmail.scheduled_at <= now,
            ScheduledEmail.is_sent == False
        ).all()

        if pending_emails:
            logger.info(f"Processing {len(pending_emails)} scheduled emails")
            
        for email in pending_emails:
            print(f"Sending scheduled email to {email.to_email}")
            success, failed_list = send_bulk_emails(
                from_role=email.from_email,
                to_list=email.to_email.split(','),
                subject=email.subject,
                body=email.body,
                content_type=email.content_type,
                attachments=email.attachments.split(',') if email.attachments else [],
                template_name=email.template_name
            )
            
            if success:
                email.is_sent = True
                db.session.commit()
            else:
                logger.warning(f"Failed to send scheduled email to: {', '.join(failed_list)}")

def start_scheduler(app):
        logger.info("Starting email scheduler")
        scheduler = BackgroundScheduler()
        scheduler.add_job(send_scheduled_emails, 'interval', seconds=30, args=[app])
        scheduler.start()