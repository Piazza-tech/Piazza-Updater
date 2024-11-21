import os
import asyncio
import dotenv
from datetime import datetime, timezone
import base64
from typing import Dict, Any
import argparse
from goldenverba.server.api import manager, client_manager
from goldenverba.server.helpers import LoggerManager
from goldenverba.server.types import Credentials, FileConfig, FileStatus
from src.wikipedia import WikipediaDataProcessor

def create_fileconfig(article_data: dict, rag_config: dict, overwrite: bool=False) -> FileConfig:
    """Create a FileConfig object from article data."""
    original_content = article_data['text'].encode('utf-8')
    encoded_content = base64.b64encode(original_content).decode('utf-8')
    
    return FileConfig(
        fileID=f"wiki_{article_data['page_id']}",
        filename=article_data['title'],
        isURL=False,
        overwrite=overwrite,
        extension="txt",
        source=article_data['source_link'],
        content=encoded_content,
        labels=article_data['labels'],
        rag_config=rag_config,
        file_size=len(original_content),
        status=FileStatus.READY,
        metadata=article_data['metadata'],
        status_report={}
    )

async def process_batch(client, batch: list[Dict[str, Any]], rag_config: dict, logger: LoggerManager):
    """Process a batch of articles concurrently."""
    tasks = []
    for article_data in batch:
        file_config = create_fileconfig(article_data, rag_config)
        tasks.append(manager.import_document(client, file_config, logger))
    return await asyncio.gather(*tasks)

async def process_static_data(data_processor: WikipediaDataProcessor, client, rag_config, logger, batch_size: int = 10):
    """
    Process the initial Wikipedia dump data in batches and upload them.
    
    Args:
        data_processor: Instance of WikipediaDataProcessor.
        client: Client connection to the server.
        rag_config: RAG configuration.
        logger: Logger instance.
        batch_size: Number of articles to process per batch.
        limit: Maximum number of articles to process (for testing).
    """
    current_batch = []

    for article_data in data_processor.process_data():
        current_batch.append(article_data)
        # Process batch when it reaches the desired size
        if len(current_batch) >= batch_size:
            await process_batch(client, current_batch, rag_config, logger)
            current_batch = []

    # Process any remaining articles in the final batch
    if current_batch:
        await process_batch(client, current_batch, rag_config, logger)

    print("Finished processing static data.")

async def fetch_recent_changes_continuously(data_processor: WikipediaDataProcessor, client, rag_config, logger, batch_size: int=10, interval_minutes: int=5):
    """
    Fetch recent Wikipedia changes every specified interval and upload them.
    
    Args:
        data_processor: Instance of WikipediaDataProcessor.
        client: Client connection to the server.
        rag_config: RAG configuration.
        logger: Logger instance.
        interval_minutes: Minutes to wait between each fetch of recent changes.
    """
    while True:
        print(f"Fetching recent changes at {datetime.now(timezone.utc).isoformat()}")
        
        current_batch = []
        
        # Fetch recent changes from the last interval
        for change in data_processor.get_recent_changes(minutes=interval_minutes):
            current_batch.append(change)
            # Process batch when it reaches the desired size
            if len(current_batch) >= batch_size:
                await process_batch(client, current_batch, rag_config, logger)
                current_batch = []

        # Process any remaining articles in the final batch
        if current_batch:
            await process_batch(client, current_batch, rag_config, logger)

        # Wait for the next interval
        await asyncio.sleep(interval_minutes * 60)

def get_production_mode(args):
    # Check if args.production is set and is a boolean
    production_mode = getattr(args, 'production', None)
    
    # If args.production is not set, check the environment variable
    if production_mode is None:
        env_value = os.getenv('PRODUCTION', 'False')  # Default to 'False' as a string
        production_mode = env_value.lower() == 'true'  # Convert to boolean

    return production_mode

# Function to parse command-line arguments
def parse_arguments():
    parser = argparse.ArgumentParser(description="Run the data processing script.")
    parser.add_argument('--production', action='store_true', help="Specify if running in production mode.")
    return parser.parse_args()

async def main():
    # Parse command-line arguments
    args = parse_arguments()
    dotenv.load_dotenv()
    # Initialize logger
    logger = LoggerManager()
    
    # Set up credentials and connect to the client
    credentials = Credentials(deployment="Docker", url="weaviate", key="")
    client = await client_manager.connect(credentials)
    production = get_production_mode(args)
    
    try:
        # Fetch the rag_config from the server
        rag_config = await manager.load_rag_config(client)
        if not rag_config:
            raise Exception("rag_config is empty. Cannot proceed.")

        # Initialize the data processor
        data_processor = WikipediaDataProcessor(production=production)

        # Process the static data first
        await process_static_data(data_processor, client, rag_config, logger, 1)

        # Start fetching recent changes continuously
        await fetch_recent_changes_continuously(data_processor, client, rag_config, logger, 1, 5)

    finally:
        await client.close()

if __name__ == "__main__":
    asyncio.run(main())
