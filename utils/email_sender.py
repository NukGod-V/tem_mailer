# utils/email_sender.py
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from threading import Thread, Lock
from email.utils import make_msgid
import time
import re
import os
import uuid
import traceback
from models import GmailAccount, Group, GroupMember, EmailLog, EmailStatus
from utils.logger import logger
from utils.template_loader import load_and_render_template
from utils.variable_resolver import fetch_template_variables


def is_valid_email(email):
    pattern = r"^[\w\.-]+@[\w\.-]+\.\w+$"
    result = re.match(pattern, email) is not None
    if not result:
        logger.debug(f"Email validation failed: {email}")
    return result


def fetch_sender_credentials(role):
    logger.debug(f"Fetching sender credentials for role: {role}")
    sender = GmailAccount.query.filter_by(role=role).first()
    if sender:
        logger.info(f"Found credentials for {role}: {sender.email}")
        return sender.email, sender.token
    logger.warning(f"No credentials found for role: {role}")
    return None, None


def resolve_recipients(to_list):
    logger.info(f"Resolving {len(to_list)} recipient identifiers")
    result = set()
    groups_resolved = 0
    users_resolved = 0
    not_found = 0
    
    for item in to_list:
        if item.endswith("*"):  # Group (multicast/broadcast)
            group_prefix = item[:-1]
            logger.debug(f"Looking up group: {group_prefix}")
            group = Group.query.filter(Group.name == group_prefix).first()
            if group:
                members = GroupMember.query.filter_by(group_id=group.group_id).all()
                member_emails = [m.email for m in members]
                result.update(member_emails)
                groups_resolved += 1
                logger.info(f"Resolved group '{group_prefix}' to {len(members)} emails")
                if len(member_emails) > 0:
                    display_members = member_emails[:5]
                    logger.debug(f"Group {group_prefix} members: {', '.join(display_members)}" + 
                                (f"... and {len(member_emails)-5} more" if len(member_emails) > 5 else ""))
            else:
                not_found += 1
                logger.warning(f"Group '{group_prefix}' not found")
        else:  # Single user (unicast)
            logger.debug(f"Looking up user by USN: {item}")
            member = GroupMember.query.filter_by(usn=item).first()
            if member:
                result.add(member.email)
                users_resolved += 1
                logger.info(f"Resolved USN '{item}' to {member.email}")
            else:
                not_found += 1
                logger.warning(f"USN '{item}' not found")
    
    resolved_emails = list(result)
    logger.info(f"Resolution complete: {groups_resolved} groups, {users_resolved} users, " +
                f"{not_found} not found, {len(resolved_emails)} total emails")
    return resolved_emails


def send_email_smtp(from_email, from_token, to_email, subject, body, content_type="text/html", attachments=[]):
    from models import db
    max_attempts = 3
    attempt = 0
    error_message = ""
    tracking_id = uuid.uuid4().hex
    tracking_url = f"https://tem-mailer.onrender.com/track/{tracking_id}.png" # Change domain name
    tracking_pixel = f'<img src="{tracking_url}" width="1" height="1" style="display:none;"/>'

    if content_type.lower() == "text/html":
        email_body += tracking_pixel

    while attempt < max_attempts:
        attempt += 1
        try:
            with smtplib.SMTP('smtp.gmail.com', 587) as smtp:
                smtp.starttls()
                smtp.login(from_email, from_token)

                msg = MIMEMultipart('alternative')
                msg['Subject'] = subject
                msg['From'] = from_email
                msg['To'] = to_email
                msg['Message-ID'] = make_msgid(domain=from_email.split('@')[1])

                msg.attach(MIMEText(email_body, 'html' if content_type == "text/html" else 'plain'))

                for path in attachments:
                    try:
                        filename = os.path.basename(path)
                        with open(path, 'rb') as f:
                            part = MIMEApplication(f.read())
                            part.add_header('Content-Disposition', 'attachment', filename=filename)
                            msg.attach(part)
                    except Exception as e:
                        logger.warning(f"Attachment failed: {e}")

                smtp.send_message(msg)

            # Log success
            log = EmailLog(from_email=from_email, to_email=to_email, subject=subject, body=email_body, status="sent")
            db.session.add(log)
            db.session.commit()

            db.session.add(EmailStatus(
                email_log_id=log.log_id,
                from_email=from_email,
                to_email=to_email,
                sent=True,
                tracking_id=tracking_id
            ))
            db.session.commit()

            logger.info(f"Email sent to {to_email} on attempt {attempt}")
            return True, to_email

        except Exception as e:
            error_message = str(e)
            logger.warning(f"Attempt {attempt} failed to send email to {to_email}: {e}")

    # All retries failed — log failure
    try:
        log = EmailLog(from_email=from_email, to_email=to_email, subject=subject,
                       body=email_body, status="failed", error_message=error_message)
        db.session.add(log)
        db.session.commit()
    except Exception as log_err:
        logger.error(f"Error logging failure: {log_err}")

    # Notify admin
    notify_admin_of_failure(to_email, subject, error_message)
    return False, to_email

def send_bulk_emails(from_role, to_list, subject, body, content_type="text/html", attachments=[], template_name=None):
    from app import app
    
    start_time = time.time()
    logger.info(f"Starting bulk email job: role={from_role}, recipients={len(to_list)}")
    
    # Thread-safe collection for failed emails
    failed_emails_lock = Lock()
    failed_emails = []
    
    from_email, from_token = fetch_sender_credentials(from_role)
    if not from_email or not from_token:
        logger.error(f"Could not find credentials for role '{from_role}'")
        return False, failed_emails

    # Resolve recipients inside app context
    with app.app_context():
        recipients = to_list if template_name else resolve_recipients(to_list)
        if not recipients:
            logger.error("No valid recipients resolved from input list")
            return False, failed_emails
        
    logger.info(f"Sending email from {from_email} to {len(recipients)} recipient(s)")
    threads = []
    dispatched_count = 0
    
    if attachments:
        attachment_names = [os.path.basename(path) for path in attachments]
        logger.info(f"Including {len(attachments)} attachment(s): {', '.join(attachment_names)}")
    
    def thread_wrapper(identifier):
        with app.app_context():
            # Default values
            actual_email = identifier
            final_body = body

            # Process USN with template if needed
            if '@' not in identifier and template_name:
                variables, err = fetch_template_variables(identifier)
                if err:
                    logger.warning(f"{err} — skipping: {identifier}")
                    with failed_emails_lock:
                        failed_emails.append(identifier)
                    return

                try:
                    final_body = load_and_render_template(template_name, variables)
                    actual_email = variables.get("email", identifier)
                    if not actual_email or '@' not in actual_email:
                        logger.warning(f"No valid email found for USN: {identifier}")
                        with failed_emails_lock:
                            failed_emails.append(identifier)
                        return
                except Exception as e:
                    logger.error(f"Template rendering failed for {identifier}: {e}")
                    with failed_emails_lock:
                        failed_emails.append(identifier)
                    return
            
            # Validate email format
            if not is_valid_email(actual_email):
                logger.warning(f"Invalid email format skipped: {actual_email}")
                with failed_emails_lock:
                    failed_emails.append(actual_email)
                return
                
            logger.info(f"Sending to: {actual_email}")
            success, recipient = send_email_smtp(from_email, from_token, actual_email, subject, 
                                                final_body, content_type, attachments)

            if not success:
                with failed_emails_lock:
                    failed_emails.append(recipient)

    # Create and start threads
    for recipient in recipients:
        logger.debug(f"Processing recipient: {recipient}")
        thread = Thread(target=thread_wrapper, args=(recipient,))
        thread.start()
        threads.append(thread)
        dispatched_count += 1

    logger.info(f"Dispatched {dispatched_count} emails, waiting for completion")
    
    # Wait for all threads to complete
    for i, t in enumerate(threads):
        t.join()
        if (i+1) % 10 == 0 or (i+1) == len(threads):
            logger.debug(f"Completed {i+1}/{len(threads)} email threads")

    elapsed_time = time.time() - start_time
    
    if failed_emails:
        failure_count = len(failed_emails)
        logger.warning(f"Bulk email job completed in {elapsed_time:.2f}s: {failure_count} of {len(recipients)} emails failed")
        logger.debug(f"Failed emails: {', '.join(failed_emails[:5])}" + 
                    (f"... and {len(failed_emails)-5} more" if len(failed_emails) > 5 else ""))
        return False, failed_emails
    else:
        logger.info(f"Bulk email job completed successfully in {elapsed_time:.2f}s. All {len(recipients)} emails sent")
        return True, []

def notify_admin_of_failure(failed_email, original_subject, error_message):
    from app import db
    try:
        admin_email = db.session.execute(
            "SELECT email FROM gmail_accounts WHERE is_admin = true LIMIT 1"
        ).scalar()
    except Exception as db_err:
        logger.error(f"Database error while fetching admin email: {db_err}")
        return

    if not admin_email:
        logger.error("No admin email found in gmail_accounts")
        return

    subject = f"[Mailer Alert] Failed to Send Email to {failed_email}"
    body = f"""The system failed to send an email after 3 attempts.

    Recipient: {failed_email}
    Original Subject: {original_subject}
    Error: {error_message}

    Please check the logs for more details.
    """

    try:
        from_email, from_token = fetch_sender_credentials("admin")  # assumes a 'gmail_accounts' row with role='admin'
        send_email_smtp(from_email, from_token, admin_email, subject, body, content_type="text/plain")
        logger.info(f"Admin notified about failure to send email to {failed_email}")
    except Exception as e:
        logger.error(f"Failed to notify admin: {e}")