"""Offline tests for the embedding text and update_articles.py, with Pinecone and OpenAI replaced by fakes."""
import json
import sys
import types

import pandas as pd
import pytest

import update_articles
from embedding_processor import prepare_text_for_embedding

ARTICLE = {
    'title': 'Who trusts AI?', 'date': '2026-01-28', 'slug': 'who-trusts-ai',
    'url': 'https://www.economicsobservatory.com/who-trusts-ai', 'author': [],
    'main_category': 'Science, technology & innovation',
    'secondary_categories': ['Attitudes, media & governance'],
    'related_articles': [], 'charts': [['Chart 1', 'Source: Pew']],
    'teaser': 'Teaser.', 'text': 'One.\nTwo.\nThree.\nFour.',
}


def test_embedding_text_weights_title_and_uses_first_three_paragraphs():
    assert prepare_text_for_embedding(ARTICLE) == (
        'Who trusts AI? Who trusts AI? | Teaser. | One. Two. Three. | '
        'Categories: Science, technology & innovation, Attitudes, media & governance'
    )


def test_embedding_text_truncates_long_text():
    article = {**ARTICLE, 'text': 'x' * 5000}
    assert 'x' * 1000 + '...' in prepare_text_for_embedding(article)
    assert 'x' * 1001 not in prepare_text_for_embedding(article)


def test_export_frontend_data(tmp_path, monkeypatch):
    monkeypatch.setattr(update_articles, 'FRONTEND_ARTICLES_PATH', tmp_path / 'articles.json')
    monkeypatch.setattr(update_articles, 'REPO_ROOT', tmp_path)
    update_articles.export_frontend_data({'who-trusts-ai': ARTICLE})
    assert json.loads((tmp_path / 'articles.json').read_text()) == {
        'who-trusts-ai': {'title': 'Who trusts AI?', 'date': '2026-01-28', 'slug': 'who-trusts-ai',
                          'url': 'https://www.economicsobservatory.com/who-trusts-ai'}
    }


@pytest.fixture
def fake_services(tmp_path, monkeypatch):
    """Fake Pinecone index holding 'indexed' and 'orphan'; fake embedder that fails on slugs containing 'fail'."""
    index_ids = {'indexed', 'orphan'}
    upserted, deleted = [], []

    class FakeIndex:
        def list(self):
            yield sorted(index_ids)

        def fetch(self, ids):
            return types.SimpleNamespace(vectors={i: {} for i in ids if i in index_ids})

        def delete(self, ids):
            index_ids.difference_update(ids)
            deleted.extend(ids)

    class FakePineconeManager:
        def __init__(self):
            self.index = FakeIndex()

        def list_article_ids(self):
            return set(index_ids)

        def upsert_articles(self, df, verbose):
            upserted.extend(df['slug'])
            index_ids.update(df['slug'])

    class FakeEmbeddingProcessor:
        def process_articles(self, articles, force_reembed):
            return pd.DataFrame([{'slug': s, 'embedding': [0.0]} for s in articles if 'fail' not in s])

    monkeypatch.setitem(sys.modules, 'pinecone_manager', types.SimpleNamespace(PineconeManager=FakePineconeManager))
    monkeypatch.setitem(sys.modules, 'embedding_processor',
                        types.SimpleNamespace(ArticleEmbeddingProcessor=FakeEmbeddingProcessor))
    monkeypatch.setattr(update_articles, 'EMBEDDINGS_BACKUP_DIR', tmp_path / 'embeddings')
    monkeypatch.setattr(update_articles, 'REPO_ROOT', tmp_path)
    monkeypatch.setattr(update_articles.time, 'sleep', lambda seconds: None)
    return types.SimpleNamespace(upserted=upserted, deleted=deleted, index_ids=index_ids)


def test_sync_uploads_only_articles_missing_from_pinecone(fake_services, tmp_path):
    articles = {'indexed': ARTICLE, 'new-one': ARTICLE, 'new-two': ARTICLE}
    assert sorted(update_articles.sync_pinecone(articles)) == ['new-one', 'new-two']
    assert sorted(fake_services.upserted) == ['new-one', 'new-two']
    assert len(list((tmp_path / 'embeddings').glob('embeddings_*.pkl'))) == 1


def test_sync_is_a_no_op_when_up_to_date(fake_services):
    assert update_articles.sync_pinecone({'indexed': ARTICLE}) == []
    assert fake_services.upserted == []


def test_sync_reports_embedding_failures_and_uploads_the_rest(fake_services, caplog):
    uploaded = update_articles.sync_pinecone({'new-one': ARTICLE, 'will-fail': ARTICLE})
    assert uploaded == ['new-one']
    assert 'Failed to embed 1 articles' in caplog.text
    assert 'orphan' in caplog.text  # vectors without a matching article are reported


def test_permalink_move_uploads_new_vector_then_deletes_old(fake_services):
    # 'indexed' was renamed to 'indexed-renamed' on the site; 'orphan' is unrelated and must be left alone
    uploaded = update_articles.sync_pinecone({'indexed-renamed': ARTICLE}, remove={'indexed', 'orphan-not-indexed'})
    assert uploaded == ['indexed-renamed']
    assert fake_services.deleted == ['indexed']
    assert fake_services.index_ids == {'indexed-renamed', 'orphan'}


def test_old_vector_kept_if_article_still_in_dataset(fake_services):
    update_articles.sync_pinecone({'indexed': ARTICLE}, remove={'indexed'})
    assert fake_services.deleted == []


def test_forced_articles_are_re_embedded_even_if_indexed(fake_services):
    assert update_articles.sync_pinecone({'indexed': ARTICLE}, force={'indexed'}) == ['indexed']


class FakeProcessor:
    """Stands in for ArticleProcessor: serves pre-baked scrapes by URL and doesn't write to disk."""
    def __init__(self, articles, pages):
        self.articles, self.pages, self.saves = articles, pages, 0

    def scrape_article(self, url):
        page = self.pages[url]
        if isinstance(page, Exception):
            raise page
        return dict(page)

    def _save_articles(self):
        self.saves += 1


def wp_post(wp_id, slug, modified='2026-10-05T12:00:00'):
    url = f"https://www.economicsobservatory.com/{slug}"
    return {'wp_id': wp_id, 'url': url, 'slug': slug, 'title': ARTICLE['title'], 'date': ARTICLE['date'],
            'modified': modified}


def test_apply_plan_moves_rescrapes_and_protects_records():
    from article_sync import plan_sync
    site = 'https://www.economicsobservatory.com'
    stored = {
        'old-slug': {**ARTICLE, 'slug': 'old-slug', 'url': f"{site}/old-slug", 'wp_id': 1, 'wp_modified': 'a'},
        'unchanged': {**ARTICLE, 'title': 'Unchanged', 'slug': 'unchanged', 'url': f"{site}/unchanged",
                      'wp_id': 2, 'wp_modified': 'a'},
        'lossy': {**ARTICLE, 'title': 'Lossy', 'slug': 'lossy', 'url': f"{site}/lossy", 'author': ['A. Author'],
                  'wp_id': 3, 'wp_modified': 'a'},
        'broken': {**ARTICLE, 'title': 'Broken', 'slug': 'broken', 'url': f"{site}/broken", 'wp_id': 4,
                   'wp_modified': 'a'},
    }
    index = [wp_post(1, 'new-slug'), {**wp_post(2, 'unchanged'), 'title': 'Unchanged'},
             {**wp_post(3, 'lossy'), 'title': 'Lossy'}, {**wp_post(4, 'broken'), 'title': 'Broken'}]
    pages = {
        f"{site}/new-slug": {**ARTICLE, 'title': 'Retitled'},
        f"{site}/unchanged": {**ARTICLE, 'title': 'Unchanged'},
        f"{site}/lossy": {**ARTICLE, 'title': 'Lossy', 'author': [], 'text': ''},
        f"{site}/broken": RuntimeError('timeout'),
    }
    processor = FakeProcessor(stored, pages)

    to_embed, old_slugs, review = update_articles.apply_plan(processor, plan_sync(stored, index))
    articles = processor.articles

    # Permalink change: record moved, re-scraped, re-embedded under the new slug; old vector to delete
    assert 'old-slug' not in articles
    assert articles['new-slug']['url'] == f"{site}/new-slug" and articles['new-slug']['title'] == 'Retitled'
    assert articles['new-slug']['wp_id'] == 1 and old_slugs == {'old-slug'}
    # Edit that doesn't change anything stored in Pinecone: no re-embed, but wp_modified recorded
    assert articles['unchanged']['wp_modified'] == '2026-10-05T12:00:00'
    # Lossy scrape: stored author and text kept and flagged for review
    assert articles['lossy']['author'] == ['A. Author'] and articles['lossy']['text'] == ARTICLE['text']
    assert review == [('lossy', 3, ['author', 'text'])]
    # Failed scrape: record untouched, so it's retried next run
    assert articles['broken']['wp_modified'] == 'a'
    assert to_embed == {'new-slug'}
    assert processor.saves >= 1
