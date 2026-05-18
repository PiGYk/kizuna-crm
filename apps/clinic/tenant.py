"""Thread-local tenant state for multi-tenant organization isolation."""
import threading
from contextlib import contextmanager

_thread_local = threading.local()


def set_current_org(org):
    _thread_local.organization = org


def get_current_org():
    return getattr(_thread_local, 'organization', None)


def clear_current_org():
    _thread_local.organization = None


@contextmanager
def org_context(org):
    """Виставити org у thread-local на час блоку. Потрібно для Celery tasks,
    management commands та інших non-HTTP code paths, бо OrgManager — fail-closed
    (без org поверне qs.none())."""
    previous = get_current_org()
    set_current_org(org)
    try:
        yield
    finally:
        if previous is None:
            clear_current_org()
        else:
            set_current_org(previous)
