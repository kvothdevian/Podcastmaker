import os
import re
import sys
import time
from urllib.parse import urljoin
from datetime import datetime

import requests
from bs4 import BeautifulSoup

# API Base
GUTENDEX_API_URL = "https://gutendex.com/books/"

# Output directory for saved txt files
OUTPUT_DIR = "output"

def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')

def search_books():
    """Prompts user for a search query and fetches results from Gutendex"""
    clear_screen()
    print("=== Gutenberg Essay Extractor - Search ===")
    query = input("Enter an author, title, or keyword (e.g., 'Emerson Essays'): ").strip()
    
    if not query:
        print("Search query cannot be empty.")
        return None

    print("\nSearching... Please wait.")
    
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        if query.isdigit():
            response = requests.get(GUTENDEX_API_URL, params={'ids': query}, headers=headers, timeout=15)
        else:
            response = requests.get(GUTENDEX_API_URL, params={'search': query}, headers=headers, timeout=15)
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as e:
        print(f"Error connecting to Gutenberg API: {e}")
        return None

    results = data.get('results', [])
    if not results:
        print("No books found matching your query.")
        return None

    print(f"\nFound {data.get('count')} books. Showing top 10:")
    for i, book in enumerate(results[:10], start=1):
        title = book.get('title', 'Unknown Title')
        authors = ", ".join([a.get('name', '') for a in book.get('authors', [])])
        print(f"{i}. {title} by {authors} (ID: {book.get('id')})")

    while True:
        try:
            choice = input("\nSelect a book number (1-10) or '0' to cancel: ").strip()
            if choice == '0':
                return None
            idx = int(choice) - 1
            if 0 <= idx < min(10, len(results)):
                # Ensure we have HTML or Plain text formats
                selected_book = results[idx]
                return selected_book
            print("Invalid choice, try again.")
        except ValueError:
            print("Please enter a valid number.")

def fetch_book_formats(book):
    """Finds available HTML or plain text URLs for the selected book"""
    formats = book.get('formats', {})
    
    html_url = None
    text_url = None
    
    # Prioritize HTML format
    for fmt, url in formats.items():
        if '.zip' in url:
            continue
        if 'text/html' in fmt:
            html_url = url
            break
            
    # For text format, prioritize /files/ or /cache/ URL to bypass /ebooks/ bot protection
    text_formats = []
    for fmt, url in formats.items():
        if '.zip' in url:
            continue
        if 'text/plain' in fmt:
            text_formats.append(url)
            
    if text_formats:
        # Prioritize urls with '/files/' or '/cache/'
        priority_text = [url for url in text_formats if '/files/' in url or '/cache/' in url]
        if priority_text:
            text_url = priority_text[0]
        else:
            text_url = text_formats[0]

    return html_url, text_url

def get_html_essays(html_content, base_url):
    """Parses HTML to find a Table of Contents or list of chapters/essays based on structure."""
    soup = BeautifulSoup(html_content, 'html.parser')
    essays = []
    
    # Different Gutenberg books have different structures. We will look for headers that act as chapter titles.
    # We will prioritize h2 and h3
    headers = soup.find_all(['h2', 'h3'])
    
    for idx, header in enumerate(headers):
        # We assume the text in an h2/h3 is the title.
        title = header.get_text(separator=' ', strip=True)
        # We need a way to find the end of this essay. We can define the bounds by finding the next sibling header.
        if title and len(title.split()) > 0: # Avoid empty headers
             essays.append((title, header))

    # If that fails (or gives too few), we can look for links in a Table of Contents (less reliable for direct extraction without fetching more pages, but often Gutenberg books are single HTML files)
    if len(essays) < 2:
        print("HTML Header search returned few results. Trying TOC links...")
        # Search for typical TOC anchors
        toc_links = soup.find_all('a', href=re.compile(r'^#'))
        for link in toc_links:
             title = link.get_text(separator=' ', strip=True)
             if title:
                # Find the target of the anchor to use as the start point, but this is complex to map to an endpoint
                 pass # We skip this for now as header-based parsing is much more reliable for single page HTML

    return essays

def get_text_essays(text_content):
    """Parses plain text to find chapters/essays using Regex."""
    # This is a fallback and can be error-prone depending on the book's formatting
    essays = []
    # Common chapter/essay regex patterns (e.g. CHAPTER I, ESSAY V, etc)
    # We capture the title
    pattern = re.compile(r'^(?:CHAPTER|ESSAY) \w+[\.\:\-]* ?(.*)$', re.MULTILINE | re.IGNORECASE)
    
    matches = list(pattern.finditer(text_content))
    for i, match in enumerate(matches):
        start_idx = match.start()
        end_idx = matches[i+1].start() if i + 1 < len(matches) else len(text_content)
        title = match.group(0).strip()
        essays.append((title, text_content[start_idx:end_idx]))

    return essays

def select_essay(essays):
    """Prompts user to select an essay from the list."""
    if not essays:
        print("Could not automatically detect distinct chapters/essays in this document.")
        return None

    print("\n--- Available Essays/Chapters ---")
    for i, (title, _) in enumerate(essays, start=1):
        print(f"{i}. {title}")
    
    while True:
        try:
            choice = input(f"\nSelect an essay to extract (1-{len(essays)}) or '0' to cancel: ").strip()
            if choice == '0':
                return None
            idx = int(choice) - 1
            if 0 <= idx < len(essays):
                return essays[idx]
            print("Invalid choice, try again.")
        except ValueError:
            print("Please enter a valid number.")


def extract_html_essay_content(start_element, next_element=None):
    """Extracts text between two HTML elements."""
    extracted_text = []
    current_element = start_element.next_element
    
    while current_element and current_element != next_element:
        # If it's a string element, add it.
        if isinstance(current_element, str):
            # We don't want script/style text
            if current_element.parent.name not in ['script', 'style']:
                text = current_element.strip()
                if text:
                    extracted_text.append(text)
        current_element = current_element.next_element

    return " ".join(extracted_text)

def clean_text_for_tts(text):
    """
    Cleans the extracted text to make it optimal for TTS.
    - Removes Gutenberg boilerplate.
    - Normalizes spacing and line breaks.
    - Handles old essay artifacts (e.g., words broken by hyphens across lines, excess newlines).
    """
    # Normalize carriage returns to standard newlines for robust processing on Windows
    text = text.replace('\r\n', '\n')

    # 1. Remove Boilerplate (Aggressive truncation)
    # If the text somehow includes the footer (e.g., if it's the last essay), cleanly slice it off.
    boilerplate_footer_markers = [
        "*** end of the project gutenberg ebook",
        "*** end of this project gutenberg ebook",
        "***end of the project gutenberg ebook",
        "end of project gutenberg",
        "end of the project gutenberg"
    ]
    
    lower_text = text.lower()
    for marker in boilerplate_footer_markers:
        index = lower_text.find(marker)
        if index != -1:
            text = text[:index]
            lower_text = lower_text[:index] # Update lower_text for subsequent checks
            
    # Remove header boilerplate if it leaked in
    boilerplate_start_markers = [
        "*** start of the project gutenberg ebook",
        "*** start of this project gutenberg ebook",
        "***start of the project gutenberg ebook"
    ]
    for marker in boilerplate_start_markers:
        index = lower_text.find(marker)
        if index != -1:
            # Find the end of that line
            end_of_line = text.find('\n', index)
            if end_of_line != -1:
                text = text[end_of_line:]
                lower_text = lower_text[end_of_line:]


    # 2. Fix old essay formatting (Hyphenation across line breaks)
    # Old books often break words across lines like "repor-\nted". We want "reported"
    text = re.sub(r'([a-zA-Z])-\n([a-zA-Z])', r'\1\2', text)
    
    # 3. Normalize whitespace
    # Replace multiple spaces with a single space
    text = re.sub(r' +', ' ', text)
    
    # Replace multiple newlines with a single newline (or two for paragraphs). 
    # For TTS, double newlines are usually the best pause indicator for a new paragraph.
    # First, replace single newlines (that aren't part of a double newline) with spaces
    # This fixes lines wrapped artificially in the raw text block
    text = re.sub(r'(?<!\n)\n(?!\n)', ' ', text)
    
    # Then ensure block separations are cleanly two newlines
    text = re.sub(r'\n{3,}', '\n\n', text)

    return text.strip()

def fetch_historical_context(author: str, title: str) -> str:
    """
    Fetches a brief historical/biographical context summary from Wikipedia.
    Capped at 400 words to stay safely under 500 words.
    """
    query = ""
    if author and author.lower() != "unknown author":
        query = author
    elif title:
        query = title
        
    if not query:
        return ""
        
    print(f"  Searching Wikipedia for context on: {query}...")
    headers = {'User-Agent': 'TheEssayistPodcast/1.0 (https://the-essayist-podcast.com; contact@the-essayist-podcast.com)'}
    
    try:
        url = "https://en.wikipedia.org/w/api.php"
        search_params = {
            "action": "query",
            "list": "search",
            "srsearch": query,
            "format": "json"
        }
        res = requests.get(url, params=search_params, headers=headers, timeout=10)
        res.raise_for_status()
        search_data = res.json()
        
        search_results = search_data.get("query", {}).get("search", [])
        if not search_results:
            return ""
            
        # Get first result's page title
        page_title = search_results[0]["title"]
        
        # Fetch introductory summary of the page
        content_params = {
            "action": "query",
            "prop": "extracts",
            "exintro": 1,
            "explaintext": 1,
            "titles": page_title,
            "format": "json"
        }
        content_res = requests.get(url, params=content_params, headers=headers, timeout=10)
        content_res.raise_for_status()
        content_data = content_res.json()
        
        pages = content_data.get("query", {}).get("pages", {})
        page_id = next(iter(pages))
        if page_id == "-1":
            return ""
            
        extract = pages[page_id].get("extract", "").strip()
        if not extract:
            return ""
            
        # Split into words, limit to 400 words (safely under 500)
        words = extract.split()
        if len(words) > 400:
            extract = " ".join(words[:400]) + "..."
        return f"Historical context on {page_title}:\n{extract}"
    except Exception as e:
        print(f"  Warning: Wikipedia context lookup failed: {e}")
        return ""

def get_mirror_urls(book_id, original_url, is_html):
    """Generates list of fallback mirror URLs for a given book ID."""
    book_id_str = str(book_id).strip()
    if not book_id_str.isdigit():
        return []
        
    if len(book_id_str) > 1:
        path = "/".join(book_id_str[:-1]) + "/" + book_id_str + "/"
    else:
        path = "0/" + book_id_str + "/"
        
    mirrors = [
        "https://mirrors.xmission.com/gutenberg/",
        "https://aleph.pglaf.org/",
        "https://mirror.cs.odu.edu/gutenberg/",
        "http://mirror.csclub.uwaterloo.ca/gutenberg/"
    ]
    
    urls = []
    for mirror in mirrors:
        if is_html:
            urls.append(f"{mirror}{path}{book_id_str}-h/{book_id_str}-h.htm")
        else:
            filename = os.path.basename(original_url) if original_url else f"{book_id_str}-0.txt"
            urls.append(f"{mirror}{path}{filename}")
            # Also append a generic fallback filename just in case
            if filename != f"{book_id_str}.txt":
                urls.append(f"{mirror}{path}{book_id_str}.txt")
    return urls

def fetch_url_with_fallback(original_url, book_id, is_html):
    """
    Attempts to download from the original Gutenberg URL first with a custom User-Agent.
    If it fails, attempts to download from a list of mirrors.
    """
    headers = {
        'User-Agent': 'TheEssayistPodcast/1.0 (https://the-essayist-podcast.com; contact@the-essayist-podcast.com)'
    }
    
    if original_url:
        try:
            print(f"Downloading from Project Gutenberg: {original_url}")
            res = requests.get(original_url, headers=headers, timeout=15)
            res.raise_for_status()
            return res
        except Exception as e:
            print(f"  Main Gutenberg site download failed or timed out: {e}")
            
    print("  Attempting mirror fallbacks...")
    mirror_urls = get_mirror_urls(book_id, original_url, is_html)
    for m_url in mirror_urls:
        try:
            print(f"  Trying mirror: {m_url}")
            res = requests.get(m_url, headers=headers, timeout=10)
            res.raise_for_status()
            print("  Mirror download successful!")
            return res
        except Exception as e:
            print(f"    Mirror failed: {e}")
            
    return None

def main():
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)

    book = search_books()
    if not book: return

    book_id = book.get('id')
    print(f"\nFetching formats for: {book.get('title')}")
    html_url, text_url = fetch_book_formats(book)
    
    essays = []
    content_format = "unknown"
    success = False

    if html_url:
        res = fetch_url_with_fallback(html_url, book_id, is_html=True)
        if res:
            try:
                content_format = "html"
                base_url = res.url
                essays = get_html_essays(res.text, base_url)
                if essays:
                    success = True
                else:
                    print("HTML parsing yielded no essays. Attempting text fallback...")
            except Exception as e:
                print(f"Failed to parse HTML: {e}. Attempting text fallback...")
            
    if not success and text_url:
        res = fetch_url_with_fallback(text_url, book_id, is_html=False)
        if res:
            try:
                content_format = "text"
                essays = get_text_essays(res.text)
                success = True
            except Exception as e:
                print(f"Failed to parse Plain Text: {e}")
            
    if not success:
        print("Error: No readable text or HTML format could be downloaded for this book.")
        return

    # Select Essay
    selection = select_essay(essays)
    if not selection: return
    
    title = selection[0]
    raw_content = ""

    print(f"Extracting content for: {title}")
    
    # Extraction
    if content_format == "html":
        header_element = selection[1]
        # Find the next header globally in the document to define the end bound, not just as a sibling
        next_header = header_element.find_next(['h2', 'h3'])
        raw_content = extract_html_essay_content(header_element, next_header)
    else:
        raw_content = selection[1]

    print("Cleaning text for TTS output...")
    cleaned_text = clean_text_for_tts(raw_content)

    if not cleaned_text:
        print("Error: Extraction resulted in empty text. The selected section might be empty or formatting could not be parsed.")
        return

    # Output
    safe_title = re.sub(r'[^a-zA-Z0-9]', '_', title)
    filename = f"{OUTPUT_DIR}/{safe_title[:30]}_{datetime.now().strftime('%Y%m%d%H%M%S')}.txt"
    
    with open(filename, 'w', encoding='utf-8') as f:
        f.write(cleaned_text)

    print(f"\nSuccess! Kept it clean and neat. Saved to: {filename}")
    print("This file is pre-processed and ready for your TTS pipeline.")
    
    # Smooth automatic podcast generation flow
    try:
        from podcast_generator import run_podcast_generation
        print("\n" + "="*50)
        print("  Launching Podcast Generator")
        print("="*50)
        
        episode_input = input("Enter episode number (default: 1): ").strip()
        episode_num = 1
        if episode_input.isdigit():
            episode_num = int(episode_input)
            
        authors = ", ".join([a.get('name', '') for a in book.get('authors', [])]) or "Unknown Author"
        
        run_podcast_generation(
            essay_path=filename,
            title=title,
            author=authors,
            episode_num=episode_num
        )
    except Exception as e:
        print(f"\n[ERROR] Failed to run podcast generation: {e}")
    
if __name__ == "__main__":
    try:
         main()
    except KeyboardInterrupt:
         print("\nOperation cancelled by user.")
         sys.exit(0)
    except Exception as e:
         print(f"\nAn error occurred: {e}")
