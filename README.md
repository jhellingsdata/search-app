



#### Dependencies

- uvicorn
- fastapi
- slowapi
- pandas
- pinecone
- requests
- bs4
- tqdm
- python-dotenv
- boto3
- openai


#### How to create venv and install dependencies

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

#### Updating articles

New articles are scraped, embedded and uploaded with one command — see [backend/UPDATING.md](backend/UPDATING.md).

```bash
cd backend
uv sync                                  # one-time: create .venv
uv run inspect_pipeline.py check         # is the scraper still reading the site correctly?
uv run update_articles.py --dry-run      # what's new?
uv run update_articles.py                # scrape → embed → Pinecone → frontend data
```
