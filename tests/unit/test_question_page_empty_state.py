"""Empty question results stay useful without changing the analysis snapshot."""

from copy import deepcopy

import pytest

from healthzip.analytics.body_metrics import analyze_questions
from healthzip.db.repository import Repository
from healthzip.ui import question_page


class _PageOutput:
    def __init__(self):
        self.messages = []

    def _record(self, *values, **kwargs):
        self.messages.append(" ".join(str(value) for value in values))

    markdown = _record
    caption = _record
    write = _record


@pytest.fixture
def empty_repo(tmp_path):
    repo = Repository(tmp_path / "empty_questions.sqlite")
    try:
        yield repo
    finally:
        repo.close()


def _empty_question(repo, question_id):
    return analyze_questions(
        repo,
        question_ids=[question_id],
        window_start="2026-11-03T00:00:00+08:00",
        window_end="2026-11-10T00:00:00+08:00",
        cutoff_time="2026-11-10T00:00:00+08:00",
        timezone_name="Asia/Shanghai",
    )[0]


@pytest.mark.parametrize("question_id", ["W5", "W6"])
def test_empty_question_keeps_observation_and_only_shows_useful_next_steps(
    empty_repo, monkeypatch, question_id
):
    question = _empty_question(empty_repo, question_id)
    assert question["report_status"] == "no_records"
    assert not question["association"] and not question["steps"]
    before = deepcopy(question)
    page = _PageOutput()
    monkeypatch.setattr(question_page, "st", page)

    question_page.render_question(question, repo=empty_repo)

    assert question == before
    assert question["observation"] in page.messages
    steps = page.messages[page.messages.index("下一步") + 1:]
    assert steps
    advice = "\n".join(steps)
    if question_id == "W5":
        assert all(term in advice for term in ("范围", "来源", "身体", "体重", "已有值", "日期", "设置", "导入与同步"))
    else:
        assert all(term in advice for term in ("范围", "来源", "睡眠", "SDNN", "导入", "日期"))
        assert "共同" in advice or "配对" in advice


@pytest.mark.parametrize("question_id", ["W5", "W6"])
def test_existing_question_steps_remain_visible_and_unchanged(
    empty_repo, monkeypatch, question_id
):
    question = _empty_question(empty_repo, question_id)
    question["steps"] = ["核对记录的来源与日期。", "补充已经完成的实际记录。"]
    before = deepcopy(question)
    page = _PageOutput()
    monkeypatch.setattr(question_page, "st", page)

    question_page.render_question(question, repo=empty_repo)

    assert question == before
    assert page.messages.count("下一步") == 1
    assert page.messages[page.messages.index("下一步") + 1:] == question["steps"]
