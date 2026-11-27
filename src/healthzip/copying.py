"""Copies of computed results; never serialization or scientific normalization."""

_ATOMIC_TYPES = frozenset({type(None), bool, int, float, str})


class _NeedsDeepcopy(Exception):
    pass


def isolated_copy(value, memo=None):
    """Copy plain JSON graphs quickly; use deepcopy for every extension graph.

    No custom hook runs during the fast attempt. If an extension is found,
    deepcopy starts again from the original root, preserving hook order, memo
    aliases and source lifetimes. An explicit caller memo always uses deepcopy.
    """
    from copy import deepcopy

    if memo is not None:
        return deepcopy(value, memo)
    try:
        return _copy_json(value, {})
    except _NeedsDeepcopy:
        pass
    # Release the rejected attempt's traceback and partial graph first.
    return deepcopy(value)


def _copy_json(value, memo):
    value_type = type(value)
    if value_type in _ATOMIC_TYPES:
        return value
    identity = id(value)
    if identity in memo:
        return memo[identity]
    if value_type is dict:
        cloned = {}
        memo[identity] = cloned
        for key, item in value.items():
            copied_item = item if type(item) in _ATOMIC_TYPES else _copy_json(item, memo)
            copied_key = key if type(key) in _ATOMIC_TYPES else _copy_json(key, memo)
            cloned[copied_key] = copied_item
    elif value_type is list:
        cloned = []
        memo[identity] = cloned
        cloned.extend(item if type(item) in _ATOMIC_TYPES else _copy_json(item, memo)
                      for item in value)
    else:
        raise _NeedsDeepcopy
    return cloned
