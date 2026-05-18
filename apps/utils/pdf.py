from django.template.loader import render_to_string
from django.http import HttpResponse


def render_pdf(template_name, context, filename='document.pdf', request=None):
    """Генерує PDF з Django шаблону через WeasyPrint."""
    try:
        from weasyprint import HTML
    except ImportError:
        return HttpResponse('WeasyPrint не встановлено', status=500)

    if request:
        context['request'] = request

    html_string = render_to_string(template_name, context)
    base_url = request.build_absolute_uri('/') if request else None
    pdf = HTML(string=html_string, base_url=base_url).write_pdf()
    response = HttpResponse(pdf, content_type='application/pdf')
    response['Content-Disposition'] = f'filename="{filename}"'
    return response
