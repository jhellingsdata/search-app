import logging
from typing import Optional, Union
import pandas as pd
from article_processor import ArticleProcessor, ArticleInfo
from embedding_processor import ArticleEmbeddingProcessor
from pinecone_manager import PineconeManager
import os
from datetime import datetime
from bs4 import BeautifulSoup

class ArticleUpdater:
    """Handles targeted updates of specific articles."""
    
    def __init__(self):
        self.article_processor = ArticleProcessor()
        self.embedding_processor = ArticleEmbeddingProcessor()
        self.pinecone_manager = PineconeManager()


    def update_single_article(self, 
                            identifier: str,
                            old_slug: Optional[str] = None,
                            force_reembed: bool = True) -> bool:
        """
        Update a single article by URL or slug.
        
        Args:
            identifier: Article URL or slug
            old_slug: Previous slug if the article's slug has changed
            force_reembed: Whether to force re-embedding even if article was previously embedded
            
        Returns:
            bool: True if update was successful
        """
        try:
            # Extract new slug from identifier
            new_slug = identifier.split('/')[-1] if '/' in identifier else identifier
            logging.info(f"Processing update for new slug: {new_slug}")
            
            # If old_slug provided, verify it exists in our data
            if old_slug and old_slug in self.article_processor.articles:
                logging.info(f"Found existing article with old slug: {old_slug}")
            elif old_slug:
                logging.warning(f"Provided old slug {old_slug} not found in existing articles")
            
            # Create ArticleInfo object for the target article
            if '/' in identifier:
                # If URL provided, need to fetch basic info first
                logging.info(f"Fetching article info from URL: {identifier}")
                try:
                    article_info = self.article_processor.get_article_info_from_url(identifier)
                    logging.info(f"Successfully fetched article info: {article_info}")
                except Exception as e:
                    logging.error(f"Error fetching article info: {str(e)}")
                    raise
            else:
                # If slug provided, construct URL and fetch info
                url = f"https://www.economicsobservatory.com/{new_slug}"
                logging.info(f"Fetching article info from constructed URL: {url}")
                try:
                    article_info = self.article_processor.get_article_info_from_url(url)
                    logging.info(f"Successfully fetched article info: {article_info}")
                except Exception as e:
                    logging.error(f"Error fetching article info: {str(e)}")
                    raise
            
            # Scrape fresh content
            logging.info("Scraping fresh article content")
            content = self.article_processor.scrape_article_content(article_info)
            
            # Update articles dictionary and save
            self.article_processor.articles[new_slug] = content
            # If we had an old slug, remove it from articles dictionary
            if old_slug and old_slug in self.article_processor.articles:
                logging.info(f"Removing old slug {old_slug} from articles dictionary")
                del self.article_processor.articles[old_slug]
            
            # Save updated articles dictionary
            self.article_processor._save_articles()
            logging.info("Article content updated successfully")
            
            if force_reembed:
                logging.info("Re-embedding article content")
                # Remove from embedded articles tracking for both old and new slugs
                if old_slug:
                    self.embedding_processor.remove_from_tracking(old_slug)
                self.embedding_processor.remove_from_tracking(new_slug)
                
                # Create DataFrame with just this article
                article_df = pd.DataFrame([content])
                article_df.index = [new_slug]
                
                # Generate new embedding
                new_embeddings_df = self.embedding_processor.process_articles(
                    {new_slug: content},
                    force_reembed=force_reembed
                )
                # Save new embeddings to file
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                new_embeddings_df.to_pickle(f'data/embeddings_{timestamp}.pkl')
                
                if not new_embeddings_df.empty:
                    logging.info("Uploading new embedding to Pinecone")
                    # Upload to Pinecone (will automatically update existing vector)
                    self.pinecone_manager.upsert_articles(new_embeddings_df, verbose=True)

                    # Remove old vector from Pinecone if it exists
                    if old_slug:
                        logging.info(f"Removing old vector with slug {old_slug} from Pinecone")
                        self.pinecone_manager.delete_article(old_slug)
                    logging.info("Vector database updated successfully")
                else:
                    logging.error("Failed to generate new embedding")
                    return False
            
            return True
            
        except Exception as e:
            logging.error(f"Error updating article {identifier}: {str(e)}")
            return False
    
    
    


# Usage example:
if __name__ == "__main__":
    updater = ArticleUpdater()
    
    # Update by URL
    success = updater.update_single_article(
        "https://www.economicsobservatory.com/how-is-the-cost-of-living-crisis-affecting-children",
        force_reembed=True
    )
    
    # Or update by slug
    success = updater.update_single_article(
        "how-is-the-cost-of-living-crisis-affecting-children",
        force_reembed=True
    )
    
    if success:
        print("Article updated successfully")
    else:
        print("Failed to update article")