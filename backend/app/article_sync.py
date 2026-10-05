"""
Reconcile the local dataset with the live WordPress site.

Articles are identified by their WordPress post ID (stored as `wp_id`), which survives permalink edits.
Records scraped before post IDs were tracked are matched by URL, then by title + publication date.
Each record also stores `wp_modified`, WordPress's last-modified time when it was scraped, so edits
made on the site since then (a fixed byline, a new title) are picked up and re-scraped.
"""
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from embedding_processor import prepare_text_for_embedding

SITE_URL = 'https://www.economicsobservatory.com'
# Fields a fresh scrape may only blank out if the stored record was also blank (see merge_scrape)
PROTECTED_FIELDS = ('title', 'main_category', 'author', 'secondary_categories', 'related_articles',
                    'charts', 'teaser', 'text')
# A re-scraped text shorter than this fraction of the stored text is treated as a scraping failure
MIN_TEXT_RATIO = 0.5


@dataclass
class SyncPlan:
    """What needs to change to bring the dataset in line with the site."""
    new: List[Dict] = field(default_factory=list)                    # posts not in the dataset
    moved: List[Tuple[str, Dict]] = field(default_factory=list)      # (stored key, post) - permalink changed
    modified: List[Tuple[str, Dict]] = field(default_factory=list)   # (stored key, post) - edited since scraped
    missing_on_site: List[str] = field(default_factory=list)         # stored keys with no published post
    matched: Dict[str, Dict] = field(default_factory=dict)           # stored key -> post, for every match

    @property
    def to_scrape(self) -> List[Tuple[str, Dict]]:
        """(dataset key after any move, post) for every article that needs scraping."""
        return ([(post['slug'], post) for post in self.new]
                + [(post['slug'], post) for _, post in self.moved]
                + self.modified)

    def restrict_to(self, wp_ids: set) -> 'SyncPlan':
        return SyncPlan(
            new=[p for p in self.new if p['wp_id'] in wp_ids],
            moved=[(k, p) for k, p in self.moved if p['wp_id'] in wp_ids],
            modified=[(k, p) for k, p in self.modified if p['wp_id'] in wp_ids],
            matched={k: p for k, p in self.matched.items() if p['wp_id'] in wp_ids},
        )


def normalise_title(title: str) -> str:
    return re.sub(r'\W+', ' ', title).strip().lower()


def plan_sync(articles: Dict[str, Dict], wp_index: List[Dict], refresh_all: bool = False,
              force_wp_ids: Optional[set] = None) -> SyncPlan:
    """Match WordPress posts to stored records and work out what is new, moved, edited or gone."""
    force_wp_ids = force_wp_ids or set()
    by_wp_id = {a['wp_id']: key for key, a in articles.items() if a.get('wp_id')}
    by_url = {a['url'].rstrip('/').lower(): key for key, a in articles.items()}
    by_title_date = {(normalise_title(a['title']), a['date']): key for key, a in articles.items()}

    plan, unmatched = SyncPlan(), set(articles)
    for post in wp_index:
        candidates = [by_wp_id.get(post['wp_id']),
                      by_url.get(post['url'].lower()),
                      by_title_date.get((normalise_title(post['title']), post['date']))]
        key = next((k for k in candidates if k in unmatched), None)
        if key is None:
            plan.new.append(post)
            continue
        unmatched.discard(key)
        plan.matched[key] = post
        if articles[key]['url'] != post['url']:
            plan.moved.append((key, post))
        elif refresh_all or post['wp_id'] in force_wp_ids or articles[key].get('wp_modified') != post['modified']:
            plan.modified.append((key, post))
    plan.missing_on_site = sorted(unmatched)
    return plan


def merge_scrape(stored: Optional[Dict], scraped: Dict) -> Tuple[Dict, List[str]]:
    """Combine a fresh scrape with the stored record, keeping stored values the scrape appears to have lost.

    Old classic-editor articles don't always parse as cleanly as block-editor ones, and some were fixed by
    hand after the original scrape. Returns the merged record and the names of any fields kept from the
    stored record, which should be reviewed.
    """
    if stored is None:
        return scraped, []
    merged, kept = dict(scraped), []
    for name in PROTECTED_FIELDS:
        if stored.get(name) and not scraped.get(name):
            merged[name] = stored[name]
            kept.append(name)
    if (stored.get('text') and scraped.get('text')
            and len(scraped['text']) < MIN_TEXT_RATIO * len(stored['text'])):
        merged['text'] = stored['text']
        kept.append('text')
    return merged, kept


def search_fields(article: Dict) -> tuple:
    """Everything that ends up in Pinecone: the embedding input plus the stored metadata."""
    return (prepare_text_for_embedding(article), article['title'], article['date'], article['url'],
            article['slug'], article['main_category'], article['secondary_categories'],
            [chart[0] for chart in article.get('charts', [])], article.get('teaser', ''))


def permalink_problem(url: str) -> Optional[str]:
    """Describe a non-standard permalink (anything other than /{article-title}), or None."""
    path = url.replace(SITE_URL, '').strip('/')
    if '/' in path:
        return f"nested under /{path.split('/')[0]}/"
    if path.isdigit():
        return "numeric"
    if path != path.lower():
        return "contains capitals"
    return None


def edit_link(wp_id: Optional[int]) -> str:
    return f"{SITE_URL}/wp-admin/post.php?post={wp_id}&action=edit" if wp_id else ''
