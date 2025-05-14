from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime 
from models import ScheduledEmail, db
from utils.email_sender import send_bulk_emails
import pytz

def send_scheduled_emails(app):
    with app.app_context():
        ist = pytz.timezone('Asia/Kolkata')
        now = datetime.now(ist)
        pending_emails = ScheduledEmail.query.filter(
            ScheduledEmail.scheduled_at <= now,
            ScheduledEmail.is_sent == False
        ).all()

        for email in pending_emails:
            print(f"Sending scheduled email to {email.to_email}")
            success, failed_list = send_bulk_emails( # show failed_list-------
                from_role=email.from_email,
                to_list=email.to_email.split(','),
                subject=email.subject,
                body=email.body,
                content_type=email.content_type,
                attachments=email.attachments.split(',') if email.attachments else []
            )
            if success:
                email.is_sent = True
                db.session.commit()

def start_scheduler(app):
        scheduler = BackgroundScheduler()
        scheduler.add_job(send_scheduled_emails, 'interval', seconds=30, args=[app])
        scheduler.start()
