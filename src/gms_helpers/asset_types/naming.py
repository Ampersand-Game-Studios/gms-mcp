from __future__ import annotations


def get_config(*args, **kwargs):
    from ..assets import get_config as facade_get_config

    return facade_get_config(*args, **kwargs)
