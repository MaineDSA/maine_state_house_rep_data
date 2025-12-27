import csv
import logging
import re
import time
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlencode, urlunparse

import urllib3
from bs4 import BeautifulSoup, PageElement, ResultSet, Tag
from tqdm import tqdm
from urllib3.util.retry import Retry

from .legislature_urls import HouseURL

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Rate limiting configuration
REQUEST_DELAY = 5  # seconds between requests


def extract_legislator_from_string(text: str) -> tuple[str, str, str, str]:
    """
    Extract legislator information from a municipality string.

    Args:
    text: Raw text containing district, town, member name, and party information.

    Returns:
    Tuple of (district, town, member, party). Returns empty strings if parsing fails.

    """
    if "District" not in text:
        return "", "", "", ""

    formatted_text = re.sub(r"[\r\n]", " ", text)
    formatted_text = re.sub(r"\s+", " ", formatted_text)
    logger.debug("Extracting data from municipality string: %s", formatted_text)

    # Extract town, district, member name, and party from the formatted string
    match = re.match(r"([\W\w\s()-]+)\s*-\s*District\s+(\d+)\s*-\s*(.+?)\s*\((.+)\)", formatted_text)
    if not match:
        logger.error("Regex match not found, can't extract municipality district data")
        return "", "", "", ""

    town = match.group(1).strip()
    district = match.group(2).strip()
    member = match.group(3).strip()
    party = match.group(4).strip()

    return district, town, member, party


def scrape_committees(spans_medium: ResultSet) -> str:
    """
    Extract committee information from span elements.

    Args:
    spans_medium: BeautifulSoup ResultSet containing span elements with medium font weight.

    Returns:
    Semicolon-separated string of committee names, or empty string if none found.

    """
    committees = ""
    for committees_tag in spans_medium:
        if committees_tag and isinstance(committees_tag, Tag) and committees_tag.getText() == "Committee(s):":
            committee_tag_1 = committees_tag.find_next("span").find_next("span")
            committees = committee_tag_1.getText().strip()
            committee_tag_2 = committee_tag_1.find_next_sibling("span")
            if committee_tag_2:
                committees = f"{committees}; {committee_tag_2.getText().strip()}"
                committee_tag_3 = committee_tag_2.find_next_sibling("span")
                if committee_tag_3:
                    committees = f"{committees}; {committee_tag_3.getText().strip()}"
    return committees


def scrape_detailed_legislator_info(http: urllib3.PoolManager, url: str, path: str, member: str) -> tuple[str, str, str]:
    """
    Scrape detailed information from a legislator's detail page.

    Args:
    http: urllib3 PoolManager instance for making HTTP requests.
    url: Base URL/netloc for the legislature website.
    path: URL path to the legislator's detail page.
    member: Name of the legislator (used for logging).

    Returns:
    Tuple of (email, phone, committees). Returns empty strings for missing data.

    """
    time.sleep(REQUEST_DELAY)  # Rate limiting

    url = urlunparse(("https", url, path, "", "", ""))
    logger.debug("Getting legislator data from URL: %s", url)
    response = http.request("GET", url)
    soup = BeautifulSoup(response.data, "html.parser")

    main_info = soup.find("div", id="main-info")
    if not main_info or not isinstance(main_info, Tag):
        return "", "", ""

    info_paragraph = main_info.find("p")
    if not info_paragraph or not isinstance(info_paragraph, Tag):
        return "", "", ""

    spans_medium = main_info.find_all("span", class_="font_weight_m")
    committees = scrape_committees(spans_medium)

    email = ""
    email_tag = info_paragraph.find("a", href=True)
    if not email_tag or not isinstance(email_tag, Tag):
        logger.warning("Email not found for %s", member)
    else:
        email = email_tag.getText().strip()

    phone = ""
    phone_possible = info_paragraph.find("span", class_="text_right")
    if phone_possible:
        for phone_tag in phone_possible:
            if not isinstance(phone_tag, PageElement):
                continue
            phone = phone_tag.getText().strip()
            if re.search(r"^(1\s?)?(\d{3}|\(\d{3}\))[\s\-\\.]?\d{3}[\s\-\\.]?\d{4}", phone):
                return email, phone, committees

    logger.warning("Phone not found for %s", member)
    return email, phone, committees


def collect_municipality_data(http: urllib3.PoolManager, value: str, query: str = "selectedLetter") -> list[tuple[str, str, str, str, str]]:
    """
    Collect basic municipality data and their legislator's profile page URLs.

    Args:
    http: urllib3 PoolManager instance for making HTTP requests.
    value: Query parameter value (typically a letter for alphabetical pagination).
    query: Query parameter name (default: "selectedLetter").

    Returns:
    List of tuples containing (district, town, member, party, detail_url).

    """
    time.sleep(REQUEST_DELAY)  # Rate limiting

    page_url = urlunparse(("https", HouseURL.StateLegislatureNetloc, HouseURL.MunicipalityListPath, "", urlencode({query: value}), ""))
    logger.debug("Getting legislators list from URL: %s", page_url)
    response = http.request("GET", page_url)
    soup = BeautifulSoup(response.data, "html.parser")

    table_tag = soup.find("table", class_="short-table white")
    if not table_tag or not isinstance(table_tag, Tag):
        return []

    legislators: list = []
    for table_row_tag in table_tag.find_all("tr")[2:]:  # Skip first 2 rows (header)
        row_cell = table_row_tag.find("td", class_="short-tabletdlf")
        district, town, member, party = extract_legislator_from_string(row_cell.get_text())
        row_link = table_row_tag.find("a", class_="btn btn-default", href=True)
        detail_url = row_link["href"] if row_link else ""
        legislators.append((district, town, member, party, detail_url))

    return legislators


def get_most_common_url(urls: list[str]) -> str:
    """
    Return the most common URL from a list of URLs.

    Args:
    urls: List of URL strings.

    Returns:
    The most frequently occurring URL, or empty string if list is empty.

    """
    if not urls:
        return ""
    counter = Counter(urls)
    return counter.most_common(1)[0][0]


def get_pagination(http: urllib3.PoolManager) -> list[str]:
    """
    Retrieve pagination letters/values from the municipality list page.

    Args:
    http: urllib3 PoolManager instance for making HTTP requests.

    Returns:
    List of pagination values (typically alphabetical letters).

    """
    time.sleep(REQUEST_DELAY)  # Rate limiting

    list_url = urlunparse(("https", HouseURL.StateLegislatureNetloc, HouseURL.MunicipalityListPath, "", "", ""))
    logger.debug("Getting pagination from URL: %s", list_url)
    response = http.request("GET", list_url)
    soup = BeautifulSoup(response.data, "html.parser")
    pages = soup.find("ul", class_="pagination")
    if not pages or not isinstance(pages, Tag):
        return []

    return [page.get_text() for page in pages.find_all("a")]


def main() -> None:
    """
    Scrape state rep municipality data.

    Performs the following steps:
    1. Collects basic municipality data from all paginated pages
    2. Groups legislators by name and identifies most common detail URL
    3. Scrapes detailed information once per unique legislator
    4. Combines all data and writes to CSV file
    """
    retry_strategy = Retry(total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504], respect_retry_after_header=True)
    http = urllib3.PoolManager(retries=retry_strategy)

    logger.info("Collecting municipality data from all pages...")
    letters = get_pagination(http)
    all_municipalities = []
    for letter in tqdm(letters, unit="page", desc="Collecting data"):
        legislators = collect_municipality_data(http, letter)
        all_municipalities.extend(legislators)
    logger.info("Found %d municipalities across %d pages", len(all_municipalities), len(letters))

    logger.info("Grouping legislators and finding most common URLs...")
    legislator_urls = defaultdict(list)
    legislator_records = defaultdict(list)

    for district, town, member, party, detail_url in all_municipalities:
        if member and detail_url:
            legislator_urls[member].append(detail_url)
            legislator_records[member].append((district, town, party))

    logger.info("Scraping details for %d unique legislators...", len(legislator_urls))
    legislator_details = {}

    for member in tqdm(legislator_urls.keys(), unit="legislator", desc="Scraping details"):
        most_common_url = get_most_common_url(legislator_urls[member])
        email, phone, committees = scrape_detailed_legislator_info(http, HouseURL.StateLegislatureNetloc, most_common_url, member)
        legislator_details[member] = (email, phone, committees)

    logger.info("Building final output...")
    final_data = []
    for district, town, member, party, _ in all_municipalities:
        if member in legislator_details:
            email, phone, committees = legislator_details[member]
            final_data.append((district, town, member, party, email, phone, committees))
        else:
            final_data.append((district, town, member, party, "", "", ""))

    with Path("house_municipality_data.csv").open(mode="w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerows([("District", "Town", "Member", "Party", "Email", "Phone", "Committees")])
        writer.writerows(final_data)

    logger.info("CSV file 'house_municipality_data.csv' has been created.")
    logger.info("Total records: %d, Unique legislators: %d", len(final_data), len(legislator_details))


if __name__ == "__main__":
    main()
