"""Copies of computed results; never serialization or scientific normalization."""

_ATOMIC_TYPES = frozenset({type(None), bool, int, float, str})


def isolated_copy(value, memo=None):
    """Preserve deepcopy aliases and isolation, with fast exact JSON containers.

    Subclasses, tuples and custom objects retain standard deepcopy semantics.
    The same memo is shared with fallback copies, including cyclic graphs.
    """
    value_type = type(value)
    if value_type in _ATOMIC_TYPES:
        return value if memo is None else memo.get(id(value), value)
    if memo is None:
        memo = {}
    identity = id(value)
    if identity in memo:
        return memo[identity]
    if value_type is dict:
        cloned = {}
        memo[identity] = cloned
        for key, item in value.items():
            # Match deepcopy's assignment evaluation order: value before key.
            # Extension hooks may inspect or extend the shared memo.
            copied_item = memo.get(id(item), item) if type(item) in _ATOMIC_TYPES else isolated_copy(item, memo)
            copied_key = memo.get(id(key), key) if type(key) in _ATOMIC_TYPES else isolated_copy(key, memo)
            cloned[copied_key] = copied_item
    elif value_type is list:
        cloned = []
        memo[identity] = cloned
        cloned.extend(memo.get(id(item), item) if type(item) in _ATOMIC_TYPES else isolated_copy(item, memo)
                      for item in value)
    else:
        from copy import deepcopy

        return deepcopy(value, memo)
    # A caller may reuse memo across calls, or an extension may release an
    # earlier input. Keep originals alive so their identities cannot be reused.
    memo[identity] = cloned
    memo.setdefault(id(memo), []).append(value)
    return cloned
