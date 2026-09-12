import pytest

from maxxvoice.workflows import ArticlePodcastPlanner


def test_article_is_split_into_editable_narration_segments():
    article = " ".join(f"word{i}" for i in range(250))
    plan = ArticlePodcastPlanner().plan(article, title="Test", chunk_words=100)

    assert plan.version == "1"
    assert plan.title == "Test"
    assert len(plan.segments) == 3
    assert plan.segments[0].speaker == "narrator"
    assert plan.segments[0].direction


def test_plan_warns_when_source_length_misses_target():
    plan = ArticlePodcastPlanner().plan("one two three", target_duration_minutes=10)
    assert plan.warnings


def test_empty_article_is_rejected():
    with pytest.raises(ValueError, match="cannot be empty"):
        ArticlePodcastPlanner().plan("  ")
