import os
from typing import List, Dict, Optional
from pinecone import (
    Pinecone,
    ServerlessSpec,
    CloudProvider,
    AwsRegion,
    Metric,
    VectorType,
    Vector
)
from datetime import datetime
import pandas as pd
from tqdm import tqdm
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

class PineconeManager:
    def __init__(self, 
                 index_name: str = "eco-articles",
                 dimension: int = 1536):  # dimension for text-embedding-3-small
        """
        Initialise Pinecone manager.
        
        Args:
            index_name: Name for the Pinecone index
            dimension: Dimensionality of the embedding vectors
        """
        self.index_name = index_name
        self.dimension = dimension
        
        # Initialise Pinecone
        self.pc = Pinecone(
            api_key=os.getenv('PINECONE_API_KEY')
        )
        
        # Create index if it doesn't exist
        self._create_index_if_not_exists()
        
        # Get index description to get host
        desc = self.pc.describe_index(name=self.index_name)
        
        # Connect to index
        self.index = self.pc.Index(host=desc.host)
    
    def _create_index_if_not_exists(self):
        """Create Pinecone index if it doesn't already exist."""
        existing_indexes = self.pc.list_indexes()
        
        if self.index_name not in [index.name for index in existing_indexes]:
            print(f"Creating new index: {self.index_name}")
            self.pc.create_index(
                name=self.index_name,
                dimension=self.dimension,
                metric=Metric.COSINE,
                spec=ServerlessSpec(
                    cloud=CloudProvider.AWS,
                    region=AwsRegion.US_EAST_1
                )
            )
    
    def upsert_articles(self, embeddings_df: pd.DataFrame, batch_size: int = 100, verbose: bool = True):
        """
        Upload article embeddings to Pinecone. Will update existing articles if they exist.
        
        Args:
            embeddings_df: DataFrame containing embeddings and metadata
            batch_size: Number of vectors to upsert in each batch
            verbose: If True, prints information about updates vs new insertions
        """
        if verbose:
            # Check which articles already exist
            existing_slugs = set()
            for slug in embeddings_df['slug']:
                try:
                    fetch_result = self.index.fetch(ids=[slug])
                    if fetch_result.vectors == {}:
                        continue
                    existing_slugs.add(slug)
                except:
                    continue
            
            print(f"Found {len(existing_slugs)} existing articles that will be updated")
            print(f"{len(embeddings_df) - len(existing_slugs)} new articles will be inserted")
        total_batches = len(embeddings_df) // batch_size + (1 if len(embeddings_df) % batch_size != 0 else 0)
        
        for i in tqdm(range(0, len(embeddings_df), batch_size), total=total_batches):
            batch_df = embeddings_df.iloc[i:i+batch_size]
            
            vectors = []
            for _, row in batch_df.iterrows():
                # Prepare metadata
                metadata = {
                    'title': row['title'],
                    'date': row['date'],
                    'date_timestamp': row['date_timestamp'],
                    'url': row['url'],
                    'main_category': row['main_category'],
                    'slug': row['slug'],
                    'secondary_categories': row['secondary_categories'],
                    'charts': row['charts'],
                    'teaser': row['teaser']
                }
                
                # Create vector object
                vector = Vector(
                    id=row['slug'],
                    values=row['embedding'],
                    metadata=metadata
                )
                vectors.append(vector)
            
            # Upsert batch
            self.index.upsert(vectors=vectors)

    def update_article_metadata(self, slug: str, metadata: Dict):
        """Update metadata for an article by slug."""
        # Check keys in metadata are valid
        valid_keys = ['title', 'date', 'date_timestamp', 'url', 'main_category', 'secondary_categories', 'charts', 'teaser']
        for key in metadata.keys():
            if key not in valid_keys:
                raise ValueError(f"Invalid metadata key: {key}")
        
        # Update metadata
        self.index.update(
            id=slug,
            set_metadata=metadata
        )
    
    def search(self, 
              query_vector: List[float], 
              top_k: int = 5,
              filter_category: Optional[str] = None,
              date_from: Optional[str] = None,
              date_to: Optional[str] = None) -> Dict:
        """
        Search for similar articles.
        
        Args:
            query_vector: Embedding vector to search with
            top_k: Number of results to return
            filter_category: Optional category to filter by
            date_from: Optional start date (format: 'YYYY-MM-DD')
            date_to: Optional end date (format: 'YYYY-MM-DD')
        """
        # Prepare filter conditions
        filter_dict = {}
        
        if filter_category:
            filter_dict["main_category"] = filter_category
        
        if date_from or date_to:
            filter_dict["date_timestamp"] = {}
            if date_from:
                from_timestamp = int(datetime.strptime(date_from, '%Y-%m-%d').timestamp())
                filter_dict["date_timestamp"]["$gte"] = from_timestamp
            if date_to:
                to_timestamp = int(datetime.strptime(date_to, '%Y-%m-%d').timestamp())
                filter_dict["date_timestamp"]["$lte"] = to_timestamp
        
        # Perform search
        results = self.index.query(
            vector=query_vector,
            top_k=top_k,
            include_metadata=True,
            filter=filter_dict if filter_dict else None
        )
        
        return results
    
    def delete_article(self, slug: str):
        """Delete an article from the index by slug."""
        self.index.delete(ids=[slug])
    
    def get_index_stats(self) -> Dict:
        """Get statistics about the index."""
        return self.index.describe_index_stats()

# Example usage:
if __name__ == "__main__":
    # Initialise manager
    manager = PineconeManager()
    
    # Load embeddings (assuming they're saved from previous step)
    # Find latest embeddings file in data folder
    # Find latest embeddings file in data folder
    embeddings_files = [f for f in os.listdir('data') if f.startswith('embeddings_') and f.endswith('.pkl')]
    # latest_embeddings_file = max(embeddings_files, key=lambda x: datetime.strptime(x.split('_')[1], '%Y%m%d_%H%M%S'))
    latest_embeddings_file = max(embeddings_files, key=lambda x: datetime.strptime(x.split('_', maxsplit=1)[1].split('.')[0], '%Y%m%d_%H%M%S'))
    embeddings_df = pd.read_pickle(f'data/{latest_embeddings_file}')
    
    # Upload to Pinecone
    manager.upsert_articles(embeddings_df)
    
    # Print index statistics
    print(manager.get_index_stats())