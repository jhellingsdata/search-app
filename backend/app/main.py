from fastapi import FastAPI, Query, HTTPException, Request
from contextlib import asynccontextmanager
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime
import uvicorn
from pinecone_manager import PineconeManager
from embedding_processor import ArticleEmbeddingProcessor
from article_processor import ArticleProcessor
import logging
import boto3
import json
import os

class SearchQuery(BaseModel):
    """Pydantic model for search requests"""
    query: str
    category: Optional[str] = None
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    top_k: Optional[int] = 10

class SearchResult(BaseModel):
    """Pydantic model for search results"""
    title: str
    url: str
    date: str
    main_category: str
    secondary_categories: List[str]
    charts: List[str]
    teaser: str
    similarity_score: float

class SearchResponse(BaseModel):
    """Pydantic model for the complete search response"""
    results: List[SearchResult]
    query: str
    total_results: int
    search_time: float

def load_articles_data():
    """Load articles data from S3 or local file"""
    if os.getenv('USE_S3', 'false').lower() == 'true':
        s3 = boto3.client('s3')
        bucket = os.getenv('S3_BUCKET')
        key = os.getenv('S3_ARTICLES_KEY')
        try:
            response = s3.get_object(Bucket=bucket, Key=key)
            content = response['Body'].read().decode('utf-8')
            return json.loads(content)
        except Exception as e:
            logging.error(f"Error loading articles data from S3: {str(e)}")
            # Fallback to local file if available
            if os.path.exists('data/all_articles.json'):
                with open('data/all_articles.json', 'r') as f:
                    return json.load(f)
            raise FileNotFoundError("No local articles data found")
    else:
        # Load from local file for development
        with open('data/all_articles.json', 'r') as f:
            return json.load(f)
        
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup code: runs before the application starts accepting requests
    articles_data = load_articles_data()
    app.state.articles = articles_data
    
    # Update the article processor with loaded data
    global article_processor
    article_processor.articles = app.state.articles
    
    logging.info(f"Loaded {len(app.state.articles)} articles at startup")
    
    yield  # This is where the application runs
    
    # Shutdown code: runs when the application is shutting down
    logging.info("Application shutting down")

limiter = Limiter(key_func=get_remote_address)
app = FastAPI(
    title="Economics Observatory Search API",
    description="API for semantic search of Economics Observatory articles",
    version="1.0.0",
    lifespan=lifespan
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
        
# Initialise our managers as global variables
# Note: In production, we may want to use FastAPI's dependency injection system
pinecone_manager = PineconeManager()
embedding_processor = ArticleEmbeddingProcessor()
article_processor = ArticleProcessor()

@app.get("/", tags=["Health Check"])
async def root():
    """Health check endpoint"""
    return {"status": "ok", "message": "Economics Observatory Search API is running"}

@app.post("/search", response_model=SearchResponse, tags=["Search"])
@limiter.limit("100/day")
async def search(request: Request, query: SearchQuery):
    """
    Search for articles using semantic similarity.
    
    - **query**: The search query text
    - **category**: Optional category filter
    - **date_from**: Optional start date (YYYY-MM-DD)
    - **date_to**: Optional end date (YYYY-MM-DD)
    - **top_k**: Number of results to return (default: 10)
    """
    try:
        start_time = datetime.now()
        
        # Generate embedding for search query
        query_embedding = embedding_processor._get_embedding(query.query)[0]
        
        # Search Pinecone
        search_results = pinecone_manager.search(
            query_vector=query_embedding,
            top_k=query.top_k,
            filter_category=query.category,
            date_from=query.date_from,
            date_to=query.date_to
        )
        
        # Format results
        formatted_results = []
        for match in search_results['matches']:
            result = SearchResult(
                title=match['metadata']['title'],
                url=match['metadata']['url'],
                date=match['metadata']['date'],
                main_category=match['metadata']['main_category'],
                secondary_categories=match['metadata'].get('secondary_categories', []),
                charts=match['metadata'].get('charts', []),
                teaser=match['metadata'].get('teaser', ''),
                similarity_score=match['score']
            )
            formatted_results.append(result)
        
        search_time = (datetime.now() - start_time).total_seconds()
        
        return SearchResponse(
            results=formatted_results,
            query=query.query,
            total_results=len(formatted_results),
            search_time=search_time
        )
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/categories", tags=["Metadata"])
async def get_categories():
    """Get list of all available categories"""
    try:
        # Extract unique categories from articles
        categories = set()
        for article in article_processor.articles.values():
            categories.add(article['main_category'])
        return sorted(list(categories))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/stats", tags=["Metadata"])
async def get_stats():
    """Get basic statistics about the article database"""
    try:
        total_articles = len(article_processor.articles)
        index_stats = pinecone_manager.get_index_stats()
        
        return {
            "total_articles": total_articles,
            "vector_count": index_stats.get('total_vector_count', 0),
            "dimension": index_stats.get('dimension', 0),
            "index_fullness": index_stats.get('index_fullness', 0),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)