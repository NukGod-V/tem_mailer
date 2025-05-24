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
    logger.debug(f"Raw to_list input: {to_list}")
    
    result = set()
    groups_resolved = 0
    users_resolved = 0
    not_found = 0

    for item in to_list:
        item = item.strip()
        logger.info(f"Processing: {item}")

        if item == "*":  # Broadcast: all users from GroupMember
            all_members = GroupMember.query.all()
            usns = [m.usn for m in all_members]
            result.update(usns)
            logger.info(f"Broadcast: resolved {len(usns)} USNs from all groups")

        elif item.endswith("*"):  # Multicast: group match (e.g., puc1*)
            group_prefix = item[:-1]
            logger.debug(f"Looking up group with name '{group_prefix}'")
            group = Group.query.filter(Group.name == group_prefix).first()
            if group:
                members = GroupMember.query.filter_by(group_id=group.group_id).all()
                usns = [m.usn for m in members]
                result.update(usns)
                groups_resolved += 1
                logger.info(f"Resolved group '{group_prefix}' to {len(members)} members")
                if usns:
                    display_usns = usns[:5]
                    logger.debug(f"Group {group_prefix} USNs: {', '.join(display_usns)}" +
                                 (f"... and {len(usns)-5} more" if len(usns) > 5 else ""))
            else:
                not_found += 1
                logger.warning(f"Group '{group_prefix}' not found")

        elif '@' in item:  # Direct email address
            result.add(item)
            logger.debug(f"Added direct email: {item}")

        else:  # Unicast USN
            member = GroupMember.query.filter_by(usn=item).first()
            if member:
                result.add(item)
                users_resolved += 1
                logger.info(f"Resolved USN '{item}' to {member.email}")
            else:
                not_found += 1
                logger.warning(f"USN '{item}' not found")

    resolved = list(result)
    logger.info(f"Resolution complete: {groups_resolved} groups, {users_resolved} users, " +
                f"{not_found} not found, {len(resolved)} total identifiers")
    return resolved


def generate_tracking_pixel(tracking_id, base_url=None):
    """Generate tracking pixel HTML with configurable base URL"""
    if base_url is None:
        # You can set this via environment variable or config
        base_url = os.getenv('TRACKING_BASE_URL')
    
    tracking_url = f"{base_url}/track/{tracking_id}.png"
    return f'<img src="{tracking_url}" width="1" height="1" style="display:none;" alt=""/>'


def send_email_smtp(from_email, from_token, to_email, subject, body, content_type="text/html", attachments=[]):
    from models import db
    from app import app
    
    if not body:
        logger.error(f"Cannot send email to {to_email} — no body provided.")
        return False, to_email
        
    max_attempts = 3
    attempt = 0
    error_message = ""
    tracking_id = uuid.uuid4().hex
    
    # Only add tracking pixel for HTML emails
    if content_type.lower() == "text/html":
        tracking_pixel = generate_tracking_pixel(tracking_id)
        email_body = (body or "") + tracking_pixel
    else:
        email_body = body
    
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

                # Create the email body part
                if content_type.lower() == "text/html":
                    msg.attach(MIMEText(email_body, 'html'))
                else:
                    msg.attach(MIMEText(email_body, 'plain'))

                # Handle attachments with better error handling
                for path in attachments:
                    try:
                        if not os.path.exists(path):
                            logger.warning(f"Attachment file not found: {path}")
                            continue
                            
                        filename = os.path.basename(path)
                        with open(path, 'rb') as f:
                            file_data = f.read()
                            if len(file_data) == 0:
                                logger.warning(f"Attachment file is empty: {path}")
                                continue
                                
                            part = MIMEApplication(file_data)
                            part.add_header('Content-Disposition', 'attachment', filename=filename)
                            msg.attach(part)
                            logger.debug(f"Attached file: {filename} ({len(file_data)} bytes)")
                    except Exception as e:
                        logger.warning(f"Failed to attach file {path}: {e}")

                # Send the email
                smtp.send_message(msg)

            # Log success in app context
            with app.app_context():
                try:
                    log = EmailLog(
                        from_email=from_email, 
                        to_email=to_email, 
                        subject=subject, 
                        body=email_body, 
                        status="sent"
                    )
                    db.session.add(log)
                    db.session.flush()  # Get the log_id
                    
                    email_status = EmailStatus(
                        email_log_id=log.log_id,
                        from_email=from_email,
                        to_email=to_email,
                        sent=True,
                        tracking_id=tracking_id
                    )
                    db.session.add(email_status)
                    db.session.commit()
                    
                    logger.info(f"Email sent to {to_email} on attempt {attempt} (tracking: {tracking_id})")
                except Exception as db_err:
                    logger.error(f"Database logging error: {db_err}")
                    db.session.rollback()

            return True, to_email

        except smtplib.SMTPAuthenticationError as e:
            error_message = f"SMTP Authentication failed: {str(e)}"
            logger.error(f"SMTP Auth error for {to_email}: {error_message}")
            break  # Don't retry auth errors
            
        except smtplib.SMTPRecipientsRefused as e:
            error_message = f"Recipient refused: {str(e)}"
            logger.error(f"Recipient refused {to_email}: {error_message}")
            break  # Don't retry recipient errors
            
        except smtplib.SMTPServerDisconnected as e:
            error_message = f"SMTP server disconnected: {str(e)}"
            logger.warning(f"SMTP disconnected for {to_email} on attempt {attempt}: {error_message}")
            time.sleep(1)  # Brief pause before retry
            
        except Exception as e:
            error_message = f"Unexpected error: {str(e)}"
            logger.warning(f"Attempt {attempt} failed to send email to {to_email}: {error_message}")
            if attempt < max_attempts:
                time.sleep(1)  # Brief pause before retry

    # All retries failed — log failure
    with app.app_context():
        try:
            log = EmailLog(
                from_email=from_email, 
                to_email=to_email, 
                subject=subject,
                body=email_body, 
                status="failed", 
                error_message=error_message
            )
            db.session.add(log)
            db.session.commit()
            logger.error(f"Email failed to {to_email} after {max_attempts} attempts: {error_message}")
        except Exception as log_err:
            logger.error(f"Error logging failure: {log_err}")

    # Notify admin
    try:
        notify_admin_of_failure(to_email, subject, error_message)
    except Exception as notify_err:
        logger.error(f"Failed to notify admin: {notify_err}")
        
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
        recipients = resolve_recipients(to_list)
        if not recipients:
            logger.error("No valid recipients resolved from input list")
            return False, failed_emails
        
    logger.info(f"Sending email from {from_email} to {len(recipients)} recipient(s)")
    threads = []
    dispatched_count = 0
    
    if attachments:
        # Validate attachments exist before starting
        valid_attachments = []
        for path in attachments:
            if os.path.exists(path):
                valid_attachments.append(path)
                logger.debug(f"Attachment validated: {os.path.basename(path)}")
            else:
                logger.warning(f"Attachment not found, skipping: {path}")
        attachments = valid_attachments
        
        if attachments:
            attachment_names = [os.path.basename(path) for path in attachments]
            logger.info(f"Including {len(attachments)} attachment(s): {', '.join(attachment_names)}")
    
    def thread_wrapper(identifier):
        actual_email = identifier
        final_body = body or ""
        
        try:
            # Check if this is a direct email address
            is_direct_email = '@' in identifier and is_valid_email(identifier)
            
            if template_name:
                if is_direct_email:
                    # For direct emails with templates, we can't fetch variables
                    # Use the email as-is and render template with minimal variables
                    logger.warning(f"Using template with direct email {identifier} - limited variable support")
                    variables = {"email": identifier, "name": identifier.split('@')[0]}
                    final_body = load_and_render_template(template_name, variables)
                    actual_email = identifier
                else:
                    # Try fetching variables for USN
                    variables, err = fetch_template_variables(identifier)
                    if err:
                        logger.warning(f"Template variable fetch error for {identifier}: {err}")
                        with failed_emails_lock:
                            failed_emails.append(identifier)
                        return
                        
                    final_body = load_and_render_template(template_name, variables)
                    actual_email = variables.get("email")
                    if not actual_email or '@' not in actual_email:
                        logger.warning(f"No valid email found for: {identifier}")
                        with failed_emails_lock:
                            failed_emails.append(identifier)
                        return
            else:
                # Handle raw body (no template)
                if is_direct_email:
                    # Direct email with raw body - use as-is
                    actual_email = identifier
                    logger.debug(f"Using direct email: {actual_email}")
                else:
                    # USN - need to look up email
                    variables, err = fetch_template_variables(identifier)
                    if err:
                        logger.warning(f"Template variable fetch error for {identifier}: {err}")
                        with failed_emails_lock:
                            failed_emails.append(identifier)
                        return
                    actual_email = variables.get("email")
                    if not actual_email or '@' not in actual_email:
                        logger.warning(f"No valid email found for: {identifier}")
                        with failed_emails_lock:
                            failed_emails.append(identifier)
                        return
                        
                if not final_body:
                    logger.error(f"No body provided for {identifier} and no template applied.")
                    with failed_emails_lock:
                        failed_emails.append(identifier)
                    return
                    
            # Final check for email format
            if not is_valid_email(actual_email):
                logger.warning(f"Invalid email format skipped: {actual_email}")
                with failed_emails_lock:
                    failed_emails.append(actual_email)
                return
                
            logger.debug(f"Sending to: {actual_email}")
            success, recipient = send_email_smtp(
                from_email, from_token, actual_email, subject,
                final_body, content_type, attachments
            )
            if not success:
                with failed_emails_lock:
                    failed_emails.append(recipient)
                    
        except Exception as e:
            logger.error(f"Thread error for {identifier}: {e}")
            logger.debug(f"Thread error traceback: {traceback.format_exc()}")
            with failed_emails_lock:
                failed_emails.append(identifier)

    def thread_launcher(identifier):
        with app.app_context():
            thread_wrapper(identifier)            

    # Create and start threads
    for recipient in recipients:
        logger.debug(f"Processing recipient: {recipient}")
        thread = Thread(target=thread_launcher, args=(recipient,))
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
    from app import app, db
    
    try:
        with app.app_context():
            admin_email = db.session.execute(
                "SELECT email FROM gmail_accounts WHERE is_admin = true LIMIT 1"
            ).scalar()
            
            if not admin_email:
                logger.error("No admin email found in gmail_accounts")
                return

            subject = f"[Mailer Alert] Failed to Send Email to {failed_email}"
            body = f"""The system failed to send an email after multiple attempts.

Recipient: {failed_email}
Original Subject: {original_subject}
Error: {error_message}

Please check the logs for more details.
"""

            from_email, from_token = fetch_sender_credentials("admin")
            if from_email and from_token:
                send_email_smtp(from_email, from_token, admin_email, subject, body, content_type="text/plain")
                logger.info(f"Admin notified about failure to send email to {failed_email}")
            else:
                logger.error("Could not find admin credentials to send notification")
                
    except Exception as e:
        logger.error(f"Failed to notify admin: {e}")
        logger.debug(f"Admin notification error traceback: {traceback.format_exc()}")