# utils/variable_resolver.py
from models import GroupMember, Group
from flask import current_app
from utils.logger import logger

def fetch_template_variables(usn):
    """
    Fetches template variables for a given USN by querying the database.
    Returns a dictionary of variables to use in email templates and error message if any.
    """
    logger.debug(f"Fetching template variables for USN: {usn}")
    
    member = GroupMember.query.filter_by(usn=usn).first()
    if not member:
        logger.warning(f"USN '{usn}' not found in database")
        return None, f"USN '{usn}' not found"

    logger.debug(f"Found member record for USN: {usn}, group_id: {member.group_id}")
    
    group = Group.query.filter_by(group_id=member.group_id).first()
    if not group:
        logger.warning(f"Group '{member.group_id}' not found for member {usn}")
        return None, f"Group '{member.group_id}' not found"

    logger.debug(f"Found group record: {group.name} (ID: {group.group_id})")

    # Convert model instances to dictionaries
    variables = member.__dict__.copy()
    variables.pop('_sa_instance_state', None)

    group_data = group.__dict__.copy()
    group_data.pop('_sa_instance_state', None)

    # Add flattened group fields
    variables["class_name"] = group_data.get("name")
    variables["class_description"] = group_data.get("description")
    
    logger.info(f"Successfully resolved template variables for USN: {usn}")
    logger.debug(f"Variable keys: {', '.join(variables.keys())}")
    
    return variables, None