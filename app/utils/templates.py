from jinja2 import Environment, FileSystemLoader
from fastapi.responses import HTMLResponse
import os

templates_dir = os.path.join(os.path.dirname(__file__), '..', 'templates')
templates_dir = os.path.abspath(templates_dir)

env = Environment(
    loader=FileSystemLoader(templates_dir),
    autoescape=True,
    cache_size=0
)


def render_template(template_name, **context):
    template = env.get_template(template_name)
    return template.render(**context)


def TemplateResponse(template_name, context):
    html = render_template(template_name, **context)
    return HTMLResponse(content=html)
