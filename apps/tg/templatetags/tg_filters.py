"""Template-фільтри для TG-чатів.

video_mime / audio_mime повертають коректний MIME за розширенням файла,
щоб <video>/<audio> у браузері мали правильний type-атрибут.
"""
from django import template

register = template.Library()


_VIDEO_MIME = {
    'mp4': 'video/mp4',
    'm4v': 'video/mp4',
    'mov': 'video/quicktime',
    'webm': 'video/webm',
    '3gp': 'video/3gpp',
    'avi': 'video/x-msvideo',
    'mkv': 'video/x-matroska',
}

_AUDIO_MIME = {
    'ogg': 'audio/ogg',
    'oga': 'audio/ogg',
    'opus': 'audio/ogg',
    'mp3': 'audio/mpeg',
    'm4a': 'audio/mp4',
    'aac': 'audio/aac',
    'wav': 'audio/wav',
    'flac': 'audio/flac',
}


@register.filter
def video_mime(name):
    """Повертає video MIME за розширенням. Fallback — video/mp4."""
    ext = (name or '').rsplit('.', 1)[-1].lower() if name and '.' in name else ''
    return _VIDEO_MIME.get(ext, 'video/mp4')


@register.filter
def audio_mime(name):
    """Повертає audio MIME за розширенням. Fallback — audio/ogg (voice)."""
    ext = (name or '').rsplit('.', 1)[-1].lower() if name and '.' in name else ''
    return _AUDIO_MIME.get(ext, 'audio/ogg')
