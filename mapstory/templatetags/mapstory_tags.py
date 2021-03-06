from django import template
from django.conf import settings
from mapstory.utils import Link

register = template.Library()

@register.simple_tag
def remote_content(path):
    return '%s/%s' % (settings.REMOTE_CONTENT_URL, path)


@register.simple_tag
def link(href, name, width=None, height=None, css_class=None):
    return Link(href, name).render(width, height, css_class)

