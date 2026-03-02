import csv
import logging
import re
import time
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlunparse

import urllib3
from bs4 import BeautifulSoup, Tag
from tqdm import tqdm
from urllib3.exceptions import HTTPError
from urllib3.util.retry import Retry

from src.legislature_urls import HouseURL

logging.basicConfig(level=logging.INFO, format="%(levelname)s:maine_state_house_rep_data:%(name)s:%(message)s")
logger = logging.getLogger(__name__)

REQUEST_DELAY = 5  # seconds between requests
HTTP_OK = 200
CSV_NAME = "house_municipality_data.csv"


def scrape_committees(soup: BeautifulSoup) -> str:
    """
    Extract committee names and roles from the list-group structure.

    Args:
        soup (BeautifulSoup):
            Legislator detail page as BeautifulSoup object

    Returns:
        str:
            'Committee Name (Role); Committee Name (Role)'

    """
    committee_entries = []

    items = soup.find_all("div", class_="list-group-item")
    for item in items:
        role_tag = item.find("span", class_="badge")

        name_tag = item.find("h6")
        if not name_tag:
            continue

        name = name_tag.get_text(strip=True)
        role = role_tag.get_text(strip=True) if role_tag else "Member"
        role = "Chair" if "Chair" in role else role

        committee_entries.append(f"{name} ({role})")

    return "; ".join(committee_entries) if committee_entries else "No committee assignments"


def scrape_detailed_legislator_info(http: urllib3.PoolManager, path: str, url: str = HouseURL.StateLegislatureNetloc) -> tuple[str, str, str]:
    """
    Extract committee names and roles from the list-group structure.

    Args:
        http (urllib3.PoolManager):
            PoolManager instance for making HTTP requests
        path (str):
            Path to specific legislator page
        url (str):
            Base URL for legislature site

    Returns:
        tuple[str, str, str]:
            (email, phone, committees)

    """
    time.sleep(REQUEST_DELAY)

    full_url = urlunparse(("https", url, path, "", "", "committees"))
    response = http.request("GET", full_url)

    if response.status != HTTP_OK:
        return "", "", ""

    soup = BeautifulSoup(response.data, "html.parser")

    email_tag = soup.find("a", href=re.compile(r"^mailto:"))
    assert isinstance(email_tag, Tag)
    email = email_tag["href"].replace("mailto:", "").split("?")[0] if email_tag and isinstance(email_tag["href"], str) else ""

    phone_tag = soup.find("a", href=re.compile(r"^tel:"))
    phone = phone_tag.get_text(strip=True) if phone_tag else ""

    committees = scrape_committees(soup)

    if not all((email, phone, committees)):
        logger.error("%s: %s, %s, %s", path, email, phone, committees)

    return email, phone, committees


def extract_legislator_info_from_row(row: Tag) -> tuple[str, str, str, str, str, str] | None:
    """
    Extract basic legislator info from a single row of the municipalities list.

    Args:
        row (Tag):
            A single row (tr) of the municipalities list (tbody)

    Returns:
        tuple[str, str, str, str, str, str] | None:
            (district, town, county, member_name, party, detail_url)

    """
    logger.debug("Extracting data from row: %s", row.prettify())
    complete_row_column_count = 4

    cols = row.find_all("td")
    if len(cols) < complete_row_column_count:
        logger.warning("Row contains too few columns: %s", cols)
        return None

    town_cell = cols[0]
    town = town_cell.find("strong").get_text(strip=True) if town_cell.find("strong") else town_cell.get_text(strip=True)
    county = town_cell.find("small").get_text(strip=True) if town_cell.find("small") else ""

    district = cols[1].get_text(strip=True)

    member_cell = cols[2]
    name_span = member_cell.find("span", class_="fw-semibold")
    member_name = name_span.get_text(strip=True) if name_span else member_cell.get_text(strip=True)

    party_badge = member_cell.find("span", class_="badge")
    party = party_badge.get_text(strip=True) if party_badge else ""

    link_tag = cols[3].find("a", href=True)
    detail_url = link_tag["href"] if link_tag else ""

    logger.debug("Extracted data from row: %s", ", ".join((district, town, county, member_name, party, detail_url)))
    return district, town, county, member_name, party, detail_url


def collect_all_municipality_data(
    http: urllib3.PoolManager, url: str = HouseURL.StateLegislatureNetloc, path: str = HouseURL.MunicipalityListPath
) -> list[tuple[str, str, str, str, str, str]]:
    """
    Collect basic municipality data and their legislator's profile page URLs.

    Args:
        http (urllib3.PoolManager):
            PoolManager instance for making HTTP requests
        url (str):
            Base URL for legislature site
        path (str):
            Path to the municipalities page

    Returns:
        list[tuple]:

            .. code-block:: python

                [
                    (district, town, county, member, party, detail_url),
                    (district, town, county, member, party, detail_url),
                ]

    """
    url = urlunparse(("https", url, path, "", "", ""))
    logger.debug("Getting legislators list from URL: %s", url)

    logger.info("Fetching the municipalities table")
    response = http.request("GET", url)
    if response.status != HTTP_OK:
        err_msg = f"Page failed to load with status: {response.status}"
        raise HTTPError(err_msg)

    soup = BeautifulSoup(response.data, "html.parser")

    table = soup.find("table", id="alphaTownTable") or soup.find("table")
    if not table:
        err_msg = "Could not find the data table"
        raise Exception(err_msg)

    assert isinstance(table, Tag)
    table = table.find("tbody")
    assert isinstance(table, Tag)
    rows = table.find_all("tr")
    logger.info("Parsing %d rows from the municipalities table", len(rows))

    legislators = []
    for row in rows:
        legislator = extract_legislator_info_from_row(row)
        if legislator:
            legislators.append(legislator)

    return legislators


def main() -> None:
    retry_strategy = Retry(total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504], respect_retry_after_header=True)
    http = urllib3.PoolManager(retries=retry_strategy)

    legislator_urls = defaultdict(list)

    all_municipalities = collect_all_municipality_data(http)
    for _, _, _, member, _, detail_url in all_municipalities:
        if member and detail_url:
            legislator_urls[member].append(detail_url)

    logger.info("Scraping details for %d unique legislators...", len(legislator_urls))
    legislator_details = {}
    try:
        for member, urls in tqdm(legislator_urls.items(), unit="rep"):
            most_common_url = Counter(urls).most_common(1)[0][0]
            legislator_details[member] = scrape_detailed_legislator_info(http, most_common_url)
    except KeyboardInterrupt:
        logger.warning("\nScrape interrupted by user. Saving partial data...")

    final_data = []
    for district, town, county, member, party, _ in all_municipalities:
        if member not in legislator_details:
            continue
        email, phone, committees = legislator_details[member]
        final_data.append((district, town, county, member, party, email, phone, committees))

    with Path(CSV_NAME).open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(["District", "Town", "County", "Member", "Party", "Email", "Phone", "Committees"])
        writer.writerows(final_data)

    logger.info("CSV file '%s' has been created.", CSV_NAME)
    logger.info("Total records: %d, Unique legislators: %d", len(final_data), len(legislator_details))


if __name__ == "__main__":
    main()
