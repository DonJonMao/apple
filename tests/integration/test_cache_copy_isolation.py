"""Process-cache consumers own mutable results, including non-JSON extensions."""
from collections import defaultdict
from contextlib import closing
from copy import deepcopy

from healthzip.analytics.cache import cached, clear
from healthzip.copying import isolated_copy
from healthzip.db.repository import Repository


class AnnotatedText(str):
    pass


class ResultExtension:
    def __init__(self, payload):
        self.payload = payload


class MemoAwareKey:
    def __init__(self, value):
        self.value = value

    def __deepcopy__(self, memo):
        return "value-copied" if id(self.value) in memo else "value-not-copied"


class MemoAlias:
    def __init__(self, original, replacement):
        self.original, self.replacement = original, replacement

    def __deepcopy__(self, memo):
        memo[id(self.original)] = self.replacement
        return "extension-copied"


def test_custom_key_observes_the_same_value_copy_order_as_deepcopy():
    shared = ["record"]
    value = {MemoAwareKey(shared): shared}
    expected = deepcopy(value)
    assert expected == {"value-copied": ["record"]}
    assert isolated_copy(value) == expected


def test_extension_memo_aliases_apply_to_later_scalar_values_and_keys():
    label = "record-identity"
    value = [MemoAlias(label, "copied-identity"), label, {label: label}]
    expected = deepcopy(value)
    assert expected == ["extension-copied", "copied-identity", {"copied-identity": "copied-identity"}]
    assert isolated_copy(value) == expected
    assert isolated_copy(label, {id(label): "caller-alias"}) == "caller-alias"


def test_shared_memo_keeps_original_containers_alive_across_calls():
    original = {"rows": []}
    memo = {}
    copied = isolated_copy(original, memo)
    assert copied == original and copied is not original
    assert any(value is original for value in memo[id(memo)])
    assert any(value is original["rows"] for value in memo[id(memo)])
    assert isolated_copy(original, memo) is copied


def test_extension_replacing_a_source_container_cannot_alias_a_later_value():
    def copy_with_replacement(copier):
        class ReplaceLater:
            def __deepcopy__(self, memo):
                self.parent[0] = None
                self.parent[2] = {"stamp": 2}
                return "replacement-event"

        marker = ReplaceLater()
        parent = [{"stamp": 1}, marker, None]
        marker.parent = parent
        return copier(parent)

    expected = copy_with_replacement(deepcopy)
    actual = copy_with_replacement(isolated_copy)
    assert expected == actual == [{"stamp": 1}, "replacement-event", {"stamp": 2}]
    assert actual[0] is not actual[2]


def test_cold_and_hot_cache_preserve_aliases_without_sharing_mutations(tmp_path):
    shared = [42]
    key = AnnotatedText("observation")
    key.notes = shared
    extended = defaultdict(list, visible=shared)
    extended["cycle"] = extended
    result = {"rows": shared, "same_rows": shared, "tuple": (shared,),
              "extension": ResultExtension(shared), "subclass": extended, key: shared}
    result["self"] = result
    clear()
    try:
        with closing(Repository(tmp_path / "synthetic.sqlite3")) as repo:
            cold = cached(repo, "independent-cache-copy", {}, lambda: result, dependencies=[])
            cold["rows"].append(999)

            def should_not_recompute():
                raise AssertionError("An unchanged cache key should remain reusable")

            hot = cached(repo, "independent-cache-copy", {}, should_not_recompute, dependencies=[])
            assert hot["rows"] == [42]
            assert hot["self"] is hot
            assert hot["rows"] is hot["same_rows"] is hot["tuple"][0] is hot["extension"].payload
            assert type(hot["tuple"]) is tuple
            assert type(hot["subclass"]) is defaultdict
            assert hot["subclass"].default_factory is list
            assert hot["subclass"]["visible"] is hot["rows"]
            assert hot["subclass"]["cycle"] is hot["subclass"]
            cloned_key = next(k for k in hot if type(k) is AnnotatedText)
            assert cloned_key is not key and cloned_key.notes is hot["rows"]
            hot["rows"].append(888)
            hot["subclass"]["new"].append("consumer")
            again = cached(repo, "independent-cache-copy", {}, should_not_recompute, dependencies=[])
            assert again["rows"] == [42]
            assert "new" not in again["subclass"]
            assert again["self"] is again and again["rows"] is not hot["rows"]
    finally:
        clear()
