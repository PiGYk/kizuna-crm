"""Thread-local tenant state for multi-tenant organization isolation."""
import threading

_thread_local = threading.local()


def set_current_org(org):
    _thread_local.organization = org


def get_current_org():
    return getattr(_thread_local, 'organization', None)


def clear_current_org():
    _thread_local.organization = None
