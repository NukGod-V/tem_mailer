from jinja2 import Template
from models import EmailTemplate

def load_and_render_template(template_name, variables={}):
    template_obj = EmailTemplate.query.filter_by(name=template_name).first()
    if not template_obj:
        raise FileNotFoundError(f"Template '{template_name}' not found in DB.")

    try:
        with open(template_obj.file_path, 'r', encoding='utf-8') as f:
            raw_html = f.read()
    except FileNotFoundError:
        raise FileNotFoundError(f"File {template_obj.file_path} not found on disk.")

    template = Template(raw_html)
    return template.render(**variables)
