"""Tests for matching stored articles to WordPress posts, and for merging fresh scrapes into stored records."""
from article_sync import merge_scrape, permalink_problem, plan_sync

SITE = 'https://www.economicsobservatory.com'


def record(slug, url=None, title='A title', date='2021-01-01', **extra):
    return {'slug': slug, 'url': url or f"{SITE}/{slug}", 'title': title, 'date': date, **extra}


def post(wp_id, slug, path=None, title='A title', date='2021-01-01', modified='2026-01-01T00:00:00'):
    url = f"{SITE}/{path or slug}"
    return {'wp_id': wp_id, 'url': url, 'slug': url.split('/')[-1], 'title': title, 'date': date,
            'modified': modified}


def test_unchanged_article_needs_nothing():
    articles = {'a': record('a', wp_id=1, wp_modified='2026-01-01T00:00:00')}
    plan = plan_sync(articles, [post(1, 'a')])
    assert (plan.new, plan.moved, plan.modified, plan.missing_on_site) == ([], [], [], [])


def test_new_article():
    plan = plan_sync({}, [post(1, 'a')])
    assert [p['slug'] for p in plan.new] == ['a']


def test_edited_article_is_rescraped():
    articles = {'a': record('a', wp_id=1, wp_modified='2026-01-01T00:00:00')}
    plan = plan_sync(articles, [post(1, 'a', modified='2026-10-05T12:56:29')])
    assert [key for key, _ in plan.modified] == ['a']


def test_article_scraped_before_tracking_is_rescraped_once():
    plan = plan_sync({'a': record('a')}, [post(1, 'a')])
    assert [key for key, _ in plan.modified] == ['a']


def test_permalink_change_matched_by_post_id():
    articles = {'old-slug': record('old-slug', title='Old title', wp_id=7, wp_modified='x')}
    plan = plan_sync(articles, [post(7, 'new-slug', title='New title')])
    assert [(key, p['slug']) for key, p in plan.moved] == [('old-slug', 'new-slug')]
    assert plan.new == [] and plan.missing_on_site == []


def test_permalink_change_before_post_ids_were_tracked_matched_by_title_and_date():
    articles = {'has-coronavirus-made-anyone-better': record(
        'has-coronavirus-made-anyone-better', title='Has coronavirus made anyone better off?', date='2020-07-29')}
    plan = plan_sync(articles, [post(8166, 'has-coronavirus-made-anyone-better-off',
                                     title='Has coronavirus made anyone better off?', date='2020-07-29')])
    assert [(key, p['wp_id']) for key, p in plan.moved] == [('has-coronavirus-made-anyone-better', 8166)]


def test_nested_permalink_fixed_on_site():
    articles = {'are-lockdowns-taxes': record('are-lockdowns-taxes', url=f"{SITE}/question/are-lockdowns-taxes",
                                             wp_id=8046, wp_modified='x')}
    plan = plan_sync(articles, [post(8046, 'are-lockdowns-taxes')])
    key, moved_to = plan.moved[0]
    assert key == 'are-lockdowns-taxes' and moved_to['url'] == f"{SITE}/are-lockdowns-taxes"


def test_numeric_permalink_replaced_by_title():
    articles = {'12453': record('12453', title='Why are pubs closing?', wp_id=12453, wp_modified='x')}
    plan = plan_sync(articles, [post(12453, 'why-are-pubs-closing', title='Why are pubs closing?')])
    assert [(key, p['slug']) for key, p in plan.moved] == [('12453', 'why-are-pubs-closing')]


def test_unpublished_article_reported_not_removed():
    articles = {'a': record('a', wp_id=1, wp_modified='x'), 'gone': record('gone', title='Gone', wp_id=2)}
    plan = plan_sync(articles, [post(1, 'a', modified='x')])
    assert plan.missing_on_site == ['gone']


def test_same_title_on_different_dates_are_different_articles():
    articles = {'update': record('update', title='Is football coming home?', date='2021-07-06')}
    plan = plan_sync(articles, [post(5, 'update-ii', title='Is football coming home?', date='2021-07-09')])
    assert [p['slug'] for p in plan.new] == ['update-ii'] and plan.missing_on_site == ['update']


def test_refresh_all_and_forced_articles():
    articles = {'a': record('a', wp_id=1, wp_modified='x'), 'b': record('b', title='B', wp_id=2, wp_modified='x')}
    index = [post(1, 'a', modified='x'), post(2, 'b', title='B', modified='x')]
    assert len(plan_sync(articles, index, refresh_all=True).modified) == 2
    forced = plan_sync(articles, index, force_wp_ids={2}).restrict_to({2})
    assert [key for key, _ in forced.modified] == ['b']


def test_merge_keeps_stored_values_a_scrape_lost():
    stored = {'title': 'T', 'author': ['A. Author'], 'teaser': 'Teaser', 'text': 'x' * 1000, 'charts': [['c', 's']]}
    scraped = {'title': 'T', 'author': [], 'teaser': '', 'text': 'x' * 100, 'charts': []}
    merged, kept = merge_scrape(stored, scraped)
    assert merged == stored
    assert sorted(kept) == ['author', 'charts', 'teaser', 'text']


def test_merge_takes_genuine_updates():
    stored = {'title': 'Old', 'author': [], 'teaser': 'Teaser', 'text': 'x' * 1000}
    scraped = {'title': 'New', 'author': ['Fixed Byline'], 'teaser': 'Teaser', 'text': 'y' * 900}
    assert merge_scrape(stored, scraped) == (scraped, [])


def test_permalink_problems():
    assert permalink_problem(f"{SITE}/why-are-pubs-closing") is None
    assert permalink_problem(f"{SITE}/question/are-lockdowns-taxes") == 'nested under /question/'
    assert permalink_problem(f"{SITE}/news/11-dec-2020") == 'nested under /news/'
    assert permalink_problem(f"{SITE}/12453") == 'numeric'
    assert permalink_problem(f"{SITE}/frontlineNHS") == 'contains capitals'
