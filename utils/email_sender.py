# utils/email_sender.py
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
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
    from app import db, app
    
    start_time = time.time()
    tracking_id = uuid.uuid4().hex
    logger.debug(f"Generated tracking ID {tracking_id} for email to {to_email}")
    
    tracking_url = f"https://tem-mailer.onrender.com/track/{tracking_id}.png"
    tracking_pixel = f'<img src="{tracking_url}" width="1" height="1" style="display:none;"/>'
    
    with app.app_context(): 
        try:
            logger.debug(f"Preparing email: from={from_email}, to={to_email}, subject='{subject}'")
            
            msg = MIMEMultipart('alternative')
            msg['Subject'] = subject
            msg['From'] = from_email
            msg['To'] = to_email
            msg['Message-ID'] = make_msgid(domain=from_email.split('@')[1])

            if content_type.lower() == "text/html":
                logger.debug("Adding tracking pixel to HTML email")
                if body:
                    body += tracking_pixel
                else:
                    body = tracking_pixel
                msg.attach(MIMEText(body, 'html'))
            else:
                logger.debug("Plain text email - no tracking pixel")
                msg.attach(MIMEText(body, 'plain'))
                
            # Process attachments
            for path in attachments:
                filename = os.path.basename(path)
                logger.debug(f"Adding attachment: {filename}")
                try:
                    from email.mime.application import MIMEApplication
                    with open(path, 'rb') as f:
                        part = MIMEApplication(f.read())
                        part.add_header('Content-Disposition', 'attachment', filename=filename)
                        msg.attach(part)
                    logger.debug(f"Attachment {filename} added successfully")
                except Exception as e:
                    logger.error(f"Failed to attach file {filename}: {str(e)}")

            # Connect to SMTP server and send
            logger.debug("Connecting to SMTP server")
            with smtplib.SMTP('smtp.gmail.com', 587) as smtp:
                smtp.starttls()
                logger.debug(f"Logging in as {from_email}")
                smtp.login(from_email, from_token)
                
                logger.debug("Sending email")
                smtp.send_message(msg)
                logger.debug("Email sent via SMTP")

            # Log the sent email
            logger.debug("Logging email to database")
            log = EmailLog(from_email=from_email, to_email=to_email, subject=subject,
                          body=body, status="sent")
            db.session.add(log)
            db.session.commit()
            logger.debug(f"Email logged with ID: {log.log_id}")
            
            # Create email status record with tracking info
            status = EmailStatus(
                email_log_id=log.log_id,
                from_email=from_email,
                to_email=to_email,
                sent=True,
                tracking_id=tracking_id,
                opened=False,
                opened_at=None
            )
            try:
                db.session.add(status)
                db.session.commit()
                logger.debug(f"Email tracking status created for ID: {tracking_id}")
            except Exception as e:
                db.session.rollback()
                logger.error(f"Failed to save EmailStatus: {str(e)}")
                logger.debug(traceback.format_exc())

            elapsed_time = time.time() - start_time
            logger.info(f"Email sent to {to_email} in {elapsed_time:.2f}s")
            return True, to_email
            
        except Exception as e:
            elapsed_time = time.time() - start_time
            logger.error(f"Failed to send to {to_email} after {elapsed_time:.2f}s: {str(e)}")
            logger.debug(traceback.format_exc())
            
            try:
                log = EmailLog(from_email=from_email, to_email=to_email, subject=subject,
                               body=body, status="failed", error_message=str(e))
                db.session.add(log)
                db.session.commit()
                logger.debug(f"Failure logged with ID: {log.log_id}")
            except Exception as db_error:
                logger.error(f"Failed to log email failure: {str(db_error)}")
                
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