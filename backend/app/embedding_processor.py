import json
import pandas as pd
import numpy as np
from openai import OpenAI
from datetime import datetime
from typing import Dict, List, Tuple
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()
client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))

class ArticleEmbeddingProcessor:
    def __init__(self, 
                 embedding_model: str = "text-embedding-3-small",
                 tracking_file: str = "embedded_articles.csv",
                 text_chunk_size: int = 1000):
        """
        Initialise the embedding processor.
        
        Args:
            embedding_model: OpenAI embedding model to use
            tracking_file: CSV file to track processed articles
            text_chunk_size: Number of characters to include from article text
        """
        self.embedding_model = embedding_model
        self.tracking_file = tracking_file
        self.text_chunk_size = text_chunk_size
        self.processed_articles = self._load_or_create_tracking_file()
        
    def _load_or_create_tracking_file(self) -> pd.DataFrame:
        """Load existing tracking file or create new one if it doesn't exist."""
        if os.path.exists(self.tracking_file):
            return pd.read_csv(self.tracking_file)
        else:
            df = pd.DataFrame(columns=['slug', 'date_embedded', 'embedding_model', 'num_tokens'])
            df.to_csv(self.tracking_file, index=False)
            return df
    
    def _prepare_text_for_embedding(self, article: Dict) -> str:
        """
        Prepare article text for embedding using our enhanced strategy.
        Weight title more heavily by repeating it.
        Include teaser, start of main text, and categories.
        """
        # Get first part of main text (split by newlines to get paragraphs)
        text_paragraphs = article['text'].split('\n')
        initial_paragraphs = ' '.join(text_paragraphs[:3])  # First 3 paragraphs
        if len(initial_paragraphs) > self.text_chunk_size:
            initial_paragraphs = initial_paragraphs[:self.text_chunk_size] + '...'
            
        # Combine categories
        categories = [article['main_category']] + article['secondary_categories']
        category_text = ', '.join(categories)
        
        # Combine all elements with clear section markers
        combined_text = f"{article['title']} {article['title']} | {article['teaser']} | "\
                       f"{initial_paragraphs} | Categories: {category_text}"
        
        return combined_text.replace("\n", " ").strip()
    
    def _get_embedding(self, text: str) -> Tuple[List[float], int]:
        """Generate embedding vector and return with token count."""
        response = client.embeddings.create(
            input=[text],
            model=self.embedding_model
        )
        return response.data[0].embedding, response.usage.total_tokens
    
    def process_articles(self, articles_data: Dict, force_reembed: bool = False) -> pd.DataFrame:
        """
        Process articles that haven't been embedded yet.
        Updates tracking file and returns DataFrame with new embeddings.
        """
        new_embeddings = []
        
        for slug, article in articles_data.items():
            # Skip if already processed
            if slug in self.processed_articles['slug'].values and not force_reembed:
                continue
                
            try:
                # Prepare and generate embedding
                processed_text = self._prepare_text_for_embedding(article)
                embedding_vector, num_tokens = self._get_embedding(processed_text)
                
                # Record successful embedding
                new_embedding = {
                    'slug': slug,
                    'date_embedded': datetime.now().strftime('%Y-%m-%d'),
                    'embedding_model': self.embedding_model,
                    'num_tokens': num_tokens,
                    'embedding': embedding_vector,
                    'title': article['title'],
                    'date': article['date'],
                    'date_timestamp': int(datetime.strptime(article['date'], '%Y-%m-%d').timestamp()),
                    'url': article['url'],
                    'main_category':  article.get('main_category', ''),
                    'secondary_categories':  article.get('secondary_categories', []),
                    'charts': [chart[0] for chart in article.get('charts', [])],  # Take the first item from each sublist in charts list
                    'teaser': article.get('teaser', '')
                }
                new_embeddings.append(new_embedding)
                
                # Update tracking file
                new_row = pd.DataFrame([{
                    'slug': slug,
                    'date_embedded': datetime.now().strftime('%Y-%m-%d'),
                    'embedding_model': self.embedding_model,
                    'num_tokens': num_tokens
                }])
                self.processed_articles = pd.concat([self.processed_articles, new_row], ignore_index=True)
                self.processed_articles.to_csv(self.tracking_file, index=False)
                
            except Exception as e:
                print(f"Error processing article {slug}: {str(e)}")
                continue
        
        return pd.DataFrame(new_embeddings)
    
    def remove_from_tracking(self, slug: str):
        """Remove an article from the embedding tracking file.
        
        Used for re-embedding an article.
        """
        if os.path.exists(self.tracking_file):
            df = pd.read_csv(self.tracking_file)
            df = df[df['slug'] != slug]
            df.to_csv(self.tracking_file, index=False)

# Usage:
if __name__ == "__main__":
    # Load articles
    with open('all_articles.json', 'r') as f:
        all_articles = json.load(f)
    
    # Initialise processor
    processor = ArticleEmbeddingProcessor()
    
    # Process articles
    new_embeddings_df = processor.process_articles(all_articles)
    
    # Save new embeddings to file (may modify this later)
    if not new_embeddings_df.empty:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        # Create data folder if it doesn't exist
        os.makedirs('data', exist_ok=True)
        new_embeddings_df.to_pickle(f'data/embeddings_{timestamp}.pkl')
        print(f"Processed {len(new_embeddings_df)} new articles")
    else:
        print("No new articles to process")