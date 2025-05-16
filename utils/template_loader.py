# utils/template_loader.py
from jinja2 import Template
from models import EmailTemplate
from utils.logger import logger

def load_and_render_template(template_name, variables={}):
    logger.info(f"Loading template: {template_name}")
    
    template_obj = EmailTemplate.query.filter_by(name=template_name).first()
    if not template_obj:
        logger.error(f"Template '{template_name}' not found in database")
        raise FileNotFoundError(f"Template '{template_name}' not found in DB.")

    try:
        with open(template_obj.file_path, 'r', encoding='utf-8') as f:
            raw_html = f.read()
        logger.debug(f"Template file loaded: {template_obj.file_path}")
    except FileNotFoundError:
        logger.error(f"Template file not found: {template_obj.file_path}")
        raise FileNotFoundError(f"File {template_obj.file_path} not found on disk.")

    template = Template(raw_html)
    rendered = template.render(**variables)
    logger.debug(f"Template rendered successfully")
    return rendered