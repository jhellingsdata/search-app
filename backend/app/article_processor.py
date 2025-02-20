import requests
from bs4 import BeautifulSoup
from datetime import datetime
import json
import logging
from typing import Dict, List, Optional, Set, Tuple
from dataclasses import dataclass
import os
from tqdm import tqdm
import boto3

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('article_processing.log'),
        logging.StreamHandler()
    ]
)

@dataclass
class ArticleInfo:
    """Data class to store article information during processing."""
    slug: str
    title: str
    url: str
    date: str
    main_category: str
    
    @classmethod
    def from_list_item(cls, item: BeautifulSoup) -> 'ArticleInfo':
        """Create ArticleInfo from a BeautifulSoup item from the articles listing page."""
        content_div = item.find('div', class_='').find_all('div')[1]
        url = content_div.find('a')['href']
        return cls(
            slug=url.split('/')[-1],
            title=content_div.find('a')['title'],
            url=url,
            date=parse_date(item.find('span').get_text()),
            main_category=item.find('a', class_='primary-category').get_text()
        )

class ArticleProcessor:
    """Handles scraping, updating, and processing of articles."""
    
    def __init__(self, 
                 base_url: str = 'https://www.economicsobservatory.com',
                 articles_path: str = 'all_articles.json'):
        self.base_url = base_url
        self.articles_path = articles_path
        self.articles = self._load_existing_articles()
        self.session = requests.Session()  # Use session for better performance
        
    def _load_existing_articles(self) -> Dict:
        """Load existing articles from JSON file or return empty dict if file doesn't exist."""
        if os.path.exists(self.articles_path):
            with open(self.articles_path, 'r') as f:
                return json.load(f)
        return {}
    
    def _save_articles(self):
        """Save articles to JSON file."""
        with open(self.articles_path, 'w') as f:
            json.dump(self.articles, f)
    
    def get_page_count(self) -> int:
        """Get total number of pages from the answers listing."""
        response = self.session.get(f"{self.base_url}/answers")
        soup = BeautifulSoup(response.text, 'html.parser')
        pagination = soup.find('div', class_='pagination')
        return int(pagination.get_text().split(' ')[3])
    
    def get_articles_on_page(self, page: int) -> List[ArticleInfo]:
        """Get all articles from a specific page number."""
        url = f"{self.base_url}/answers" if page == 1 else f"{self.base_url}/answers/page/{page}"
        response = self.session.get(url)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        articles_list = soup.find('div', class_='answers__listing-left').find_all('li')
        return [ArticleInfo.from_list_item(item) for item in articles_list]
    
    def scrape_article_content(self, article: ArticleInfo) -> Dict:
        """Scrape detailed content for a single article."""
        response = self.session.get(article.url)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        try:
            # Extract all article components
            content = {
                'title': article.title,
                'date': article.date,
                'slug': article.slug,
                'url': article.url,
                'main_category': article.main_category,
                'author': self._extract_authors(soup),
                'secondary_categories': self._extract_secondary_categories(soup),
                'related_articles': self._extract_related_articles(soup),
                'charts': self._extract_charts(soup),
                'teaser': self._extract_teaser(soup),
                'text': self._extract_article_body(soup)
            }
            return content
        except Exception as e:
            logging.error(f"Error scraping article {article.url}: {str(e)}")
            raise
    
    def update_articles(self, max_pages: Optional[int] = None, skip_existing: bool = False) -> Tuple[int, int]:
        """
        Update articles database with new articles.
        
        Args:
            max_pages: Optional maximum number of pages to process
            skip_existing: If True, skip articles that have already been scraped
                         If False, re-scrape existing articles to update them
        
        Returns:
            tuple of (new articles added, articles updated)
        """
        new_articles = 0
        updated_articles = 0
        page = 1
        total_pages = min(self.get_page_count(), max_pages or float('inf'))
        
        while page <= total_pages:
            logging.info(f"Processing page {page} of {total_pages}")
            articles = self.get_articles_on_page(page)
            
            # If skipping existing articles, filter the list
            if skip_existing:
                original_count = len(articles)
                articles = [article for article in articles if article.slug not in self.articles]
                skipped = original_count - len(articles)
                if skipped > 0:
                    logging.info(f"Skipped {skipped} existing articles on page {page}")
                
                # If no new articles on this page, we can stop
                if not articles:
                    logging.info(f"No new articles found on page {page}, stopping search")
                    break
            else:
                # If not skipping, check if we have all articles from this page
                if all(article.slug in self.articles for article in articles):
                    logging.info(f"All articles on page {page} already processed")
                    break
            
            # Process each article
            for article in tqdm(articles, desc=f"Processing articles on page {page}"):
                try:
                    content = self.scrape_article_content(article)
                    if article.slug in self.articles:
                        updated_articles += 1
                    else:
                        new_articles += 1
                    self.articles[article.slug] = content
                    self._save_articles()  # Save after each successful scrape
                except Exception as e:
                    logging.error(f"Failed to process article {article.url}: {str(e)}")
                    continue
            
            page += 1
        
        return new_articles, updated_articles
    

    def get_article_info_from_url(self, url: str) -> ArticleInfo:
        """Extract basic article info from URL.
        
        Used for updating a single article.
        """
        response = self.session.get(url)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        return ArticleInfo(
            slug=url.split('/')[-1],
            title=soup.find('h1').get_text(),
            url=url,
            date=parse_date(soup.find('div', class_='article__meta').find('span').get_text().strip()),
            main_category=soup.find('a', class_='primary-category').get_text()
        )
    
    # Helper methods for content extraction
    def _extract_authors(self, soup: BeautifulSoup) -> List[str]:
        try:
            return soup.find('span', class_='author').get_text().split(', ')
        except:
            return []
    
    def _extract_teaser(self, soup: BeautifulSoup) -> str:
        try:
            return soup.find('div', class_='article__intro').get_text()
        except:
            return ''
    
    def _extract_charts(self, soup: BeautifulSoup) -> List[Tuple[str, str]]:
        charts = soup.find_all('section', class_='blocks__chart')
        try:
            charts_info = []
            for chart in charts:
                if 'wp-block-column' in chart.parent.get('class', []):
                    title = chart.parent.parent.find_previous_sibling().get_text(strip=True, separator=' ')
                    source = chart.parent.parent.find_next_sibling().get_text(strip=True, separator=' ')
                else:
                    title = chart.find_previous_sibling().get_text(strip=True, separator=' ')
                    source = chart.find_next_sibling().get_text(strip=True, separator=' ')
                charts_info.append((title, source))
            return sorted(set(charts_info), key=charts_info.index)
        except Exception as e:
            logging.warning(f"Error extracting charts: {str(e)}")
            return []
    
    def _extract_related_articles(self, soup: BeautifulSoup) -> List[Tuple[str, str]]:
        try:
            sidebar = soup.find('ul', class_='article__sidebar-links')
            return [(li.get_text(strip=True), li.find('a')['href'].split('/')[-1]) 
                    for li in sidebar.find_all('li')]
        except:
            return []
    
    def _extract_secondary_categories(self, soup: BeautifulSoup) -> List[str]:
        try:
            categories = soup.find('ul', class_=['article__sidebar-categories', 'inview'])
            return [li.get_text(strip=True) for li in categories.find_all('li')]
        except:
            return []
    
    def _extract_article_body(self, soup: BeautifulSoup) -> str:
        article_body = soup.find('div', class_=['article__body', 'article__body--padding'])
        
        # Remove unwanted header tags
        for tag in ['h4', 'h5', 'h6']:
            for element in article_body.find_all(tag):
                element.decompose()
        
        # Select relevant content
        content = BeautifulSoup(str(article_body), "html.parser").select(
            "p, h3:not(:-soup-contains('further reading')):not(:-soup-contains('experts on this')):not(:-soup-contains('find out more'))"
        )
        
        return "\n".join(p.get_text(strip=True, separator=' ') for p in content)

def parse_date(date: str) -> str:
    """Parse date from website format to ISO format."""
    try:
        return datetime.strptime(date.split('• ')[1], '%d %b %y').strftime('%Y-%m-%d')
    except:
        # On main article page, date is in format '8 Jan 2021'
        return datetime.strptime(date.split('• ')[1], '%d %b %Y').strftime('%Y-%m-%d')

# Usage example:
if __name__ == "__main__":
    processor = ArticleProcessor()
    
    # Update articles (optionally specify max_pages to limit processing)
    new_articles, updated_articles = processor.update_articles(max_pages=None)
    
    logging.info(f"Processing complete: {new_articles} new articles added, "
                f"{updated_articles} articles updated")