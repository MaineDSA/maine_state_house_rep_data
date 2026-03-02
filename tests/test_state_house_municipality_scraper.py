from collections.abc import Generator
from unittest.mock import MagicMock, patch

import pytest
import urllib3
from bs4 import BeautifulSoup, Tag

from src.main import collect_all_municipality_data, extract_legislator_info_from_row, scrape_committees, scrape_detailed_legislator_info


@pytest.fixture
def sample_committee_soup() -> BeautifulSoup:
    html = """
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
    return BeautifulSoup(html, "html.parser")


@pytest.fixture
def mock_http() -> Generator[MagicMock, None, None]:
    with patch("urllib3.PoolManager") as mocked:
        yield mocked


@pytest.fixture
def mock_sleep() -> Generator[None, None, None]:
    with patch("src.main.time.sleep", return_value=None):
        yield


def test_scrape_committees_logic(sample_committee_soup: BeautifulSoup) -> None:
    result = scrape_committees(sample_committee_soup)

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
def test_scrape_detailed_info_success(mock_http: MagicMock) -> None:
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.data = """
    <a href="mailto:rep.jane@legislature.maine.gov?subject=Hi">Email</a>
    <a href="tel:207-555-0123">207-555-0123</a>
    <div class="list-group-item"><h6>Judiciary</h6></div>
    """
    mock_http.request.return_value = mock_resp

    email, phone, committees = scrape_detailed_legislator_info(mock_http, "/path")

    assert email == "rep.jane@legislature.maine.gov"
    assert phone == "207-555-0123"
    assert "Judiciary (Member)" in committees


def test_collect_all_municipality_data_error(mock_http: MagicMock) -> None:
    mock_resp = MagicMock()
    mock_resp.status = 404
    mock_http.request.return_value = mock_resp

    with pytest.raises(urllib3.exceptions.HTTPError, match=f"Page failed to load with status: {mock_resp.status}"):
        collect_all_municipality_data(mock_http)
