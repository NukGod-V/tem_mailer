# models.py
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timezone

db = SQLAlchemy()

class User(db.Model):
    __tablename__ = 'users'
    user_id = db.Column(db.String(100), primary_key=True)
    service_name = db.Column(db.String(100), nullable=False)
    api_token = db.Column(db.String(255), unique=True, nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.now(timezone.utc))


class GmailAccount(db.Model):
    __tablename__ = 'gmail_accounts'
    id = db.Column(db.Integer, primary_key=True)
    role = db.Column(db.String(50), nullable=False)
    email = db.Column(db.String(255), nullable=False, unique=True)
    token = db.Column(db.String(255), nullable=False)


class Group(db.Model):
    __tablename__ = 'email_groups'
    group_id = db.Column(db.String(100), primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)


class GroupMember(db.Model):
    __tablename__ = 'group_members'
    group_id = db.Column(db.String(100), db.ForeignKey('email_groups.group_id', ondelete='CASCADE'), primary_key=True)
    usn = db.Column(db.String(100), primary_key=True)
    email = db.Column(db.String(255), nullable=False)


class EmailLog(db.Model):
    __tablename__ = 'email_logs'
    log_id = db.Column(db.Integer, primary_key=True)
    from_email = db.Column(db.String(255), nullable=False)
    to_email = db.Column(db.String(255), nullable=False)
    subject = db.Column(db.String(255), nullable=False)
    body = db.Column(db.Text, nullable=False)
    sent_at = db.Column(db.DateTime, default=datetime.now(timezone.utc))
    status = db.Column(db.String(50), nullable=False)
    error_message = db.Column(db.Text, nullable=True)
    # tracking_id = db.Column(db.String(100), unique=True)
    # opened = db.Column(db.Boolean, default=False)
    # opened_at = db.Column(db.DateTime, nullable=True)

class EmailTemplate(db.Model):
    __tablename__ = 'email_templates'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    file_path = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text)

class EmailAttachment(db.Model):
    __tablename__ = 'email_attachments'
    id = db.Column(db.Integer, primary_key=True)
    email_id = db.Column(db.Integer, db.ForeignKey('email_logs.log_id'), nullable=True)
    filename = db.Column(db.String(255))
    path = db.Column(db.String(255))

class EmailStatus(db.Model):
    __tablename__ = 'email_status'
    id = db.Column(db.Integer, primary_key=True)
    email_log_id = db.Column(db.Integer, db.ForeignKey('email_logs.log_id', ondelete='CASCADE'), nullable=False)
    from_email = db.Column(db.String(255), nullable=False)
    to_email = db.Column(db.String(255), nullable=False)
    sent = db.Column(db.Boolean, default=False)
    tracking_id = db.Column(db.String(100), unique=True, nullable=False)
    opened = db.Column(db.Boolean, default=False)
    opened_at = db.Column(db.DateTime, nullable=True)
    view_count = db.Column(db.Integer, default=0)

    email_log = db.relationship('EmailLog', backref=db.backref('statuses', lazy=True))

class ScheduledEmail(db.Model):
    __tablename__ = 'scheduled_emails'
    id = db.Column(db.Integer, primary_key=True)
    from_email = db.Column(db.String(255), nullable=False)
    to_email = db.Column(db.String(255), nullable=False)
    subject = db.Column(db.String(255), nullable=False)
    body = db.Column(db.Text, nullable=False)
    scheduled_at = db.Column(db.DateTime, nullable=False)
    content_type = db.Column(db.String(50), default='text/html')
    attachments = db.Column(db.Text)  # Comma-separated
    is_sent = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    template_name = db.Column(db.String(255), nullable=True)