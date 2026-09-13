from app.domain.news_filter import filter_relevant_news


def _article(headline: str, summary: str = "") -> dict:
    return {"headline": headline, "summary": summary, "url": "https://x", "source": "Reuters", "datetime": 100, "image": ""}


def test_filter_relevant_news_keeps_qqq_nq_relevant_articles():
    articles = [
        _article("Fed signals another rate cut is coming"),
        _article("Nvidia earnings beat expectations, chip demand soars"),
        _article("Local bakery wins pastry award"),  # irrelevante
    ]
    result = filter_relevant_news(articles)
    assert [a["headline"] for a in result] == [
        "Fed signals another rate cut is coming",
        "Nvidia earnings beat expectations, chip demand soars",
    ]


def test_filter_relevant_news_matches_on_summary_too():
    articles = [_article("Regional update", "Oil prices spike after OPEC announcement")]
    result = filter_relevant_news(articles)
    assert len(result) == 1


def test_filter_relevant_news_marks_important_flag():
    articles = [
        _article("Iran and Israel exchange attacks overnight"),  # HIGH_IMPACT
        _article("Nasdaq closes slightly higher on light volume"),  # relevante pero no severo
    ]
    result = filter_relevant_news(articles)
    by_headline = {a["headline"]: a["important"] for a in result}
    assert by_headline["Iran and Israel exchange attacks overnight"] is True
    assert by_headline["Nasdaq closes slightly higher on light volume"] is False


def test_filter_relevant_news_discards_all_when_nothing_matches():
    articles = [_article("City council approves new park"), _article("Weather turns cooler this weekend")]
    assert filter_relevant_news(articles) == []


def test_filter_relevant_news_empty_input():
    assert filter_relevant_news([]) == []


def test_filter_relevant_news_preserves_original_fields():
    articles = [_article("Fed holds rates steady", "")]
    result = filter_relevant_news(articles)
    assert result[0]["url"] == "https://x"
    assert result[0]["source"] == "Reuters"
    assert result[0]["datetime"] == 100
