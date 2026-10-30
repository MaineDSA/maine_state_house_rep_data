from collections.abc import Generator
from http import HTTPStatus
from unittest.mock import patch
from urllib.parse import urlunparse

import pytest
import urllib3
from bs4 import BeautifulSoup, Tag
from pytest_urllib3 import Urllib3Mock

from src.legislature_urls import HouseURL
from src.main import collect_all_municipality_data, extract_legislator_info_from_row, parse_committee_html, scrape_detailed_legislator_info


@pytest.fixture
def html_content() -> bytes:
    return b"""
    <div class="list-group">
        <div class="list-group-item">
            <span class="badge">Chair</span>
            <h6>Appropriations and Financial Affairs</h6>
        </div>
        <div class="list-group-item">
            <span class="badge">Member</span>
            <h6>Ethics Committee</h6>
        </div>
        <div class="list-group-item">
            <h6>Taxation Committee</h6>
        </div>
    </div>
    """


@pytest.fixture
def mock_sleep() -> Generator[None, None, None]:
    with patch("src.main.time.sleep", return_value=None):
        yield


def test_scrape_committees_logic(html_content: bytes) -> None:
    result = parse_committee_html(html_content)

    assert "Appropriations and Financial Affairs (Chair)" in result
    assert "Ethics Committee (Member)" in result
    assert "Taxation Committee (Member)" in result
    assert result.count(";") == 2


@pytest.mark.parametrize(
    ("html_input", "expected"),
    [
        (
            """
            <tr>
                <td><strong>Augusta</strong><small>Kennebec</small></td>
                <td>District 80</td>
                <td><span class="fw-semibold">Jane Doe</span><span class="badge">D</span></td>
                <td><a href="/member/123">Link</a></td>
            </tr>
            """,
            ("District 80", "Augusta", "Kennebec", "Jane Doe", "D", "/member/123"),
        ),
        (
            """
            <tr>
                <td>Portland</td>
                <td>District 1</td>
                <td>John Smith</td>
                <td><a href="/member/1">Link</a></td>
            </tr>
            """,
            ("District 1", "Portland", "", "John Smith", "", "/member/1"),
        ),
    ],
    ids=("complete row", "minimal data"),
)
def test_extract_legislator_info_rows(html_input: str, expected: tuple[str, str, str, str, str, str]) -> None:
    soup = BeautifulSoup(html_input, "html.parser")
    row = soup.find("tr")
    assert isinstance(row, Tag)
    result = extract_legislator_info_from_row(row)
    assert result == expected


def test_extract_legislator_info_malformed_row() -> None:
    soup = BeautifulSoup("<tr><td>Not enough data</td></tr>", "html.parser")
    row = soup.find("tr")
    assert isinstance(row, Tag)
    assert extract_legislator_info_from_row(row) is None


@pytest.mark.usefixtures("mock_sleep")
def test_scrape_detailed_info_success(urllib3_mock: Urllib3Mock) -> None:
    request_method = "GET"
    request_path = "/path"
    request_url = urlunparse(("https", HouseURL.StateLegislatureNetloc, request_path, "", "", ""))

    expected_email = "rep.jane@legislature.maine.gov"
    expected_phone = "207-555-0123"
    expected_committee = "Judiciary"

    response_text = f"""
    <a href="mailto:{expected_email}?subject=Hi">Email</a>
    <a href="tel:{expected_phone}">{expected_phone}</a>
    <div class="list-group-item"><h6>{expected_committee}</h6></div>
    """

    urllib3_mock.add_response(method=request_method, url=request_url, text=response_text)
    http = urllib3.PoolManager()

    email, phone, committees = scrape_detailed_legislator_info(http, request_path)

    assert email == expected_email
    assert phone == expected_phone
    assert committees == f"{expected_committee} (Member)"


def test_collect_all_municipality_data_error(urllib3_mock: Urllib3Mock) -> None:
    request_method = "GET"
    request_url = urlunparse(("https", HouseURL.StateLegislatureNetloc, HouseURL.MunicipalityListPath, "", "", ""))

    urllib3_mock.add_response(method=request_method, url=request_url, status_code=HTTPStatus.NOT_FOUND)
    http = urllib3.PoolManager()

    with pytest.raises(urllib3.exceptions.HTTPError, match=f"Status: {HTTPStatus.NOT_FOUND}"):
        collect_all_municipality_data(http)
