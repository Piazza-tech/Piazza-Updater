import os
import requests
import bz2
import mwxml
import mwparserfromhell
import json
from typing import Generator, Dict, Any
from datetime import datetime, timedelta, timezone
from time import sleep
from tqdm import tqdm

class WikipediaDataProcessor:
    def __init__(self, extract_folder: str = "/data/datasets/wikipedia/extracted_wikipedia", production=False):
        self.dump_url_test = "https://dumps.wikimedia.org/enwiki/latest/enwiki-latest-pages-articles1.xml-p1p41242.bz2"
        self.dump_url_prod = "https://dumps.wikimedia.org/enwiki/latest/enwiki-latest-pages-articles-multistream.xml.bz2"
        self.dump_url = self.dump_url_prod if production else self.dump_url_test
        self.dump_file = os.path.join(os.path.dirname(extract_folder), "enwiki-sample.xml.bz2")
        self.extract_folder = extract_folder
        self.production = production
        self.api_base_url = "https://en.wikipedia.org/w/api.php"

        # Check and download the dump file if necessary
        self.check_and_download_dump()
        # Check and extract the dump file if necessary
        self.check_and_extract_dump()

    def check_and_download_dump(self):
        # Check if the dump file exists
        if not os.path.exists(self.dump_file):
            # Get the directory for the dump file
            os.makedirs(os.path.abspath(os.path.dirname(self.dump_file)), exist_ok=True)

            print(f"Dump file {self.dump_file} not found.")
            self.download_wikipedia_dump()
        else:
            print(f"Dump file {self.dump_file} already exists.")

    def download_wikipedia_dump(self):
        response = requests.get(self.dump_url, stream=True)
        total_size = int(response.headers.get('content-length', 0))
        print(f"Downloading {total_size / 1048576:.2f} MB from {self.dump_url} ...")
        block_size = 1024 * 1024  # 1 MB

        with open(self.dump_file, 'wb') as file:
            # Initialize tqdm for progress tracking
            with tqdm(total=total_size, unit='MB', unit_scale=True, desc=self.dump_file) as pbar:
                for data in response.iter_content(block_size):
                    file.write(data)
                    pbar.update(len(data) / (1024 * 1024))  # Update progress bar

        print(f"Downloaded {self.dump_file}")

    def check_and_extract_dump(self):
        if not os.path.isdir(self.extract_folder) or not bool(os.listdir(self.extract_folder)):
            print(f"Extract folder {self.extract_folder} not found. Extracting...")
            os.makedirs(self.extract_folder, exist_ok=True)
            self.extract_dump()
        else:
            print(f"Extract folder {self.extract_folder} already exists.")

    def extract_dump(self):
        # Get the total size of the dump file for progress tracking
        total_size = os.path.getsize(self.dump_file)
        
        with bz2.BZ2File(self.dump_file, 'rb') as file:
            # Open the output file for writing
            with open(os.path.join(self.extract_folder, 'wikipedia.xml'), 'wb') as out_file:
                # Initialize tqdm for progress tracking
                with tqdm(total=total_size, unit='B', unit_scale=True, desc='Extracting dump') as pbar:
                    for data in iter(lambda: file.read(100 * 1024), b''):  # Read in chunks of 100 KB
                        out_file.write(data)
                        pbar.update(len(data))  # Update progress bar with the size of data written

        print(f"Extracted dump to {self.extract_folder}")
        if not self.production:
            try:
                os.remove(self.dump_file)
                print(f"Deleted dump file: {self.dump_file}")
            except OSError as e:
                print(f"Error deleting file {self.dump_file}: {e}")

    def process_data(self) -> Generator[Dict[str, Any], None, None]:
        xml_file_path = os.path.join(self.extract_folder, 'wikipedia.xml')
        
        # Count total pages in the dump file for tqdm
        with open(xml_file_path, 'rb') as file:
            dump = mwxml.Dump.from_file(file)
            total_pages = sum(1 for _ in dump)

        # Process pages with tqdm progress bar
        with open(xml_file_path, 'rb') as file:
            dump = mwxml.Dump.from_file(file)
            pages_count = 0
            for page in tqdm(dump, total=total_pages, desc="Processing Wikipedia Pages"):
                if not self.production and pages_count >= 500:
                    break
                title = page.title
                # Skip non-article pages (e.g., User:, Talk:, etc.)
                if ':' in title:
                    continue
                # Construct source link
                source_link = f"https://en.wikipedia.org/wiki/{title.replace(' ', '_')}"
                # Get the latest revision text
                try:
                    revision = next(page)  # Assuming the first revision is the latest
                except StopIteration:
                    continue  # No revisions, skip page
                text = revision.text

                if text is None or text.startswith("#REDIRECT"):
                    continue  # Skip void and REDIRECT pages

                # Parse wikitext to extract plain text
                wikicode = mwparserfromhell.parse(text)
                plain_text = wikicode.strip_code()

                # Yield the data in the standardized format
                yield {
                    'title': title,
                    'source_link': source_link,
                    'text': plain_text,
                    'page_id': page.id,
                    'labels': ['Wikipedia'],
                    'metadata': json.dumps({
                        'id': page.id,
                        'title': title
                    })
                }
                pages_count +=1
                
    def get_recent_changes(self, minutes: int = 5) -> Generator[Dict[str, Any], None, None]:
        """
        Fetch and process recent changes from Wikipedia.
        
        Args:
            minutes: Number of minutes to look back for changes (default: 5)
            
        Yields:
            Dict containing processed page information in the same format as process_data()
        """
        # Calculate the start time
        start_time = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).strftime("%Y%m%d%H%M%S")
        
        # Parameters for the API request
        params = {
            "action": "query",
            "format": "json",
            "list": "recentchanges",
            "rcstart": start_time,
            "rcdir": "newer",
            "rcnamespace": "0",  # Main namespace only
            "rclimit": "500",    # Maximum allowed limit
            "rcprop": "title|ids|timestamp|comment|user|flags|sizes",
        }
        
        processed_pages = set()  # Track processed pages to avoid duplicates
        
        while True:
            try:
                response = requests.get(self.api_base_url, params=params)
                response.raise_for_status()
                data = response.json()
                
                changes = data.get("query", {}).get("recentchanges", [])
                
                if not changes:
                    break

                pages_count = 0
                for change in tqdm(changes, desc="Processing changes", unit="change"):
                    if not self.production and pages_count >= 50:
                        break
                    page_id = change["pageid"]
                    # Skip if we've already processed this page
                    if page_id in processed_pages:
                        continue
                    processed_pages.add(page_id)
                    
                    # Get the current content of the page
                    content_params = {
                        "action": "query",
                        "format": "json",
                        "prop": "revisions",
                        "pageids": page_id,
                        "rvprop": "content",
                        "rvslots": "main"
                    }
                    
                    try:
                        content_response = requests.get(self.api_base_url, params=content_params)
                        content_response.raise_for_status()
                        content_data = content_response.json()
                        
                        # Extract the page content
                        page = next(iter(content_data["query"]["pages"].values()))
                        revision = page["revisions"][0]
                        text = revision["slots"]["main"]["*"]
                        
                        # Skip redirects
                        if text.startswith("#REDIRECT"):
                            continue
                        
                        title = page["title"]
                        source_link = f"https://en.wikipedia.org/wiki/{title.replace(' ', '_')}"
                        
                        # Parse wikitext to extract plain text
                        wikicode = mwparserfromhell.parse(text)
                        plain_text = wikicode.strip_code()
                        
                        yield {
                            'title': title,
                            'source_link': source_link,
                            'text': plain_text,
                            'page_id': page_id,
                            'labels': ['Wikipedia'],
                            'metadata': json.dumps({
                                'id': page_id,
                                'title': title,
                                'last_modified': change['timestamp'],
                                'editor': change['user'],
                                'comment': change.get('comment', '')
                            })
                        }
                        
                        # Be nice to the API
                        sleep(0.1)
                        pages_count += 1
                        
                    except Exception as e:
                        print(f"Error processing page {page_id}: {str(e)}")
                        continue
                
                # Check if there are more results
                if "continue" in data:
                    params.update(data["continue"])
                else:
                    break
                    
            except Exception as e:
                print(f"Error fetching recent changes: {str(e)}")
                break