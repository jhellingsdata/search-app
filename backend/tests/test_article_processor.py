"""Offline tests for the scraping parsers, using snippets that mirror the site's markup (October 2026)."""
import pytest
from bs4 import BeautifulSoup

from article_processor import ArticleInfo, ArticleProcessor, parse_date

LISTING_ITEM = """
<li>
  <svg></svg>
  <div>
    <div style="color: #f88461;">
      <a class="primary-category" href="https://www.economicsobservatory.com/topics/jobs-work-pay-benefits">
        Jobs, work, pay &amp; benefits</a>
      <span>• 30 Sep 26</span>
    </div>
    <div>
      <a href="https://www.economicsobservatory.com/why-are-good-jobs-concentrated-in-certain-places"
         title="Why are good jobs concentrated in certain places?">Why are good jobs concentrated in certain places?</a>
    </div>
  </div>
</li>
"""

ARTICLE_PAGE = """
<html><body>
<h1>How might the UK’s relations with China evolve?&nbsp;</h1>
<div class="article__meta">
  <a class="primary-category" href="https://www.economicsobservatory.com/topics/trade-supply-chains">
    Trade &amp; supply chains</a>
  <span>• 10 Jan 2025 <span class="author">George Magnus, Jane Doe</span></span>
</div>
<div class="article__intro">
Teaser paragraph.
</div>
<div class="article__body article__body--padding">
  <p>First paragraph.</p>
  <h3>A section heading</h3>
  <h4>Removed heading</h4>
  <p>Second <a href="#">linked</a> paragraph.</p>
  <h3>Where can I find out more?</h3>
</div>
<ul class="article__sidebar-categories inview"><li>Trade &amp; supply chains</li><li>Global economy</li></ul>
<ul class="article__sidebar-links">
  <li><a href="https://www.economicsobservatory.com/related-one">Related one</a></li>
</ul>
</body></html>
"""


@pytest.mark.parametrize('text, expected', [
    ('• 30 Sep 26', '2026-09-30'),                      # listing page
    ('• 8 Jan 21', '2021-01-08'),
    ('• 10 Jan 2025', '2025-01-10'),                    # article page
    ('• 10 Jan 2025 George Magnus', '2025-01-10'),      # article page with author inside the span
])
def test_parse_date(text, expected):
    assert parse_date(text) == expected


def test_parse_date_rejects_text_without_a_date():
    with pytest.raises(ValueError):
        parse_date('George Magnus')


def test_listing_item():
    info = ArticleInfo.from_list_item(BeautifulSoup(LISTING_ITEM, 'html.parser').li)
    assert info == ArticleInfo(
        slug='why-are-good-jobs-concentrated-in-certain-places',
        title='Why are good jobs concentrated in certain places?',
        url='https://www.economicsobservatory.com/why-are-good-jobs-concentrated-in-certain-places',
        date='2026-09-30',
        main_category='Jobs, work, pay & benefits',
    )


@pytest.fixture
def processor(tmp_path, monkeypatch):
    processor = ArticleProcessor(articles_path=str(tmp_path / 'articles.json'))

    class FakeResponse:
        text = ARTICLE_PAGE

        def raise_for_status(self):
            pass

    monkeypatch.setattr(processor.session, 'get', lambda url, **kwargs: FakeResponse())
    return processor


def test_article_info_from_url(processor):
    info = processor.get_article_info_from_url('https://www.economicsobservatory.com/how-might-the-uks-relations-with-china-evolve')
    assert info.title == 'How might the UK’s relations with China evolve?'
    assert info.date == '2025-01-10'
    assert info.main_category == 'Trade & supply chains'
    assert info.slug == 'how-might-the-uks-relations-with-china-evolve'


def test_scrape_article_content(processor):
    info = processor.get_article_info_from_url('https://www.economicsobservatory.com/how-might-the-uks-relations-with-china-evolve')
    article = processor.scrape_article_content(info)
    assert article['author'] == ['George Magnus', 'Jane Doe']
    assert article['teaser'] == 'Teaser paragraph.'
    assert article['secondary_categories'] == ['Trade & supply chains', 'Global economy']
    assert article['related_articles'] == [('Related one', 'related-one')]
    assert article['charts'] == []
    # h4-h6 and "...find out more?" headings are dropped (case-sensitive match); h3 section headings are kept
    assert article['text'] == 'First paragraph.\nA section heading\nSecond linked paragraph.'


def test_scrape_article_fetches_page_once(processor, monkeypatch):
    calls = []
    original_get = processor.session.get
    monkeypatch.setattr(processor.session, 'get', lambda url, **kwargs: calls.append(url) or original_get(url))
    article = processor.scrape_article('https://www.economicsobservatory.com/how-might-the-uks-relations-with-china-evolve')
    assert len(calls) == 1
    assert article['date'] == '2025-01-10' and article['author'] == ['George Magnus', 'Jane Doe']


def test_emails_are_removed():
    from article_processor import remove_emails
    soup = BeautifulSoup('<p>Email us at: <a class="__cf_email__" data-cfemail="2d4c">[email&#160;protected]</a>. '
                         'Or contact a.person@bristol.ac.uk today.</p>', 'html.parser')
    remove_emails(soup)
    assert soup.get_text() == 'Email us at: . Or contact today.'


def test_title_comes_from_article_heading_not_first_h1(processor, monkeypatch):
    page = ARTICLE_PAGE.replace('<h1>', '<h1 class="data-hub-heading">Data Hub.</h1><h1 class="article__title">')

    class FakeResponse:
        text = page

        def raise_for_status(self):
            pass

    monkeypatch.setattr(processor.session, 'get', lambda url, **kwargs: FakeResponse())
    assert processor.get_article_info_from_url('https://x/y').title == 'How might the UK’s relations with China evolve?'


def test_author_names_have_whitespace_collapsed(processor, monkeypatch):
    page = ARTICLE_PAGE.replace('George Magnus, Jane Doe', 'Anwen  Zhang, Mushfiq   Mobarak')

    class FakeResponse:
        text = page

        def raise_for_status(self):
            pass

    monkeypatch.setattr(processor.session, 'get', lambda url, **kwargs: FakeResponse())
    assert processor.scrape_article('https://x/y')['author'] == ['Anwen Zhang', 'Mushfiq Mobarak']
