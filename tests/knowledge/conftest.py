import pytest

from healthzip.knowledge import KnowledgeWorkbench


@pytest.fixture
def kb(tmp_path):
    w = KnowledgeWorkbench(tmp_path / "kb", environment_kind="synthetic_test")
    yield w
    w.close()
