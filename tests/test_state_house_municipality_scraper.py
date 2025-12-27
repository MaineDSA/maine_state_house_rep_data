from collections.abc import Callable, Generator
from unittest.mock import MagicMock, Mock, patch

import pytest
import urllib3
from bs4 import BeautifulSoup

from src.legislature_urls import LegislatureURL
from src.main import (
    collect_municipality_data,
    extract_legislator_from_string,
    get_most_common_url,
    get_pagination,
    scrape_committees,
    scrape_detailed_legislator_info,
)


@pytest.fixture
def mock_http() -> MagicMock:
    """Create a mock HTTP pool manager."""
    return MagicMock(spec=urllib3.PoolManager)


@pytest.fixture
def mock_http_response(mock_http: MagicMock) -> Callable:
    """Create a mock HTTP response factory."""

    def _make_response(html: str) -> MagicMock:
        mock_response = Mock()
        mock_response.data = html.encode()
        mock_http.request.return_value = mock_response
        return mock_http

    return _make_response


@pytest.fixture
def mock_house_url() -> Generator[LegislatureURL]:
    """Mock HouseURL configuration."""
    with patch("src.main.HouseURL") as mock_url:
        mock_url.StateLegislatureNetloc = "leg.maine.gov"
        mock_url.MunicipalityListPath = "/municipalities"
        yield mock_url


class TestExtractLegislatorFromString:
    """Tests for extract_legislator_from_string function."""

    @pytest.mark.parametrize(
        ("text", "expected_district", "expected_town", "expected_member", "expected_party"),
        [
            ("Manchester - District 23 - John Smith (Democrat)", "23", "Manchester", "John Smith", "Democrat"),
            ("Manchester\n\n - District 23  -   John Smith  (Democrat)", "23", "Manchester", "John Smith", "Democrat"),
            ("Weare (West) - District 5 - Jane Doe (Republican)", "5", "Weare (West)", "Jane Doe", "Republican"),
            ("Concord - District 1 - Bob Johnson (Independent)", "1", "Concord", "Bob Johnson", "Independent"),
            ("Randolph - District 53 - Michael H. Lemelin (R - Chelsea)", "53", "Randolph", "Michael H. Lemelin", "R - Chelsea"),
            ("Raymond - District 86 - Rolf A. Olsen (R - Raymond)", "86", "Raymond", "Rolf A. Olsen", "R - Raymond"),
            ("Readfield - District 57 - Tavis Rock Hasenfus (D - Readfield)", "57", "Readfield", "Tavis Rock Hasenfus", "D - Readfield"),
        ],
        ids=[
            "valid_string",
            "multiline_whitespace",
            "special_characters",
            "independent_party",
            "with_middle_initial",
            "hyphenated_name",
            "multi_word_last_name",
        ],
    )
    def test_valid_extraction(self, text: str, expected_district: str, expected_town: str, expected_member: str, expected_party: str) -> None:
        """Test extraction from valid municipality strings."""
        district, town, member, party = extract_legislator_from_string(text)

        assert district == expected_district
        assert town == expected_town
        assert member == expected_member
        assert party == expected_party

    @pytest.mark.parametrize(
        "text",
        [
            "Manchester - 23 - John Smith (Democrat)",
            "Invalid format without proper structure",
            "",
        ],
        ids=["no_district_keyword", "malformed_string", "empty_string"],
    )
    def test_invalid_extraction(self, text: str) -> None:
        """Test returns empty strings for invalid input."""
        district, town, member, party = extract_legislator_from_string(text)

        assert district == ""
        assert town == ""
        assert member == ""
        assert party == ""


class TestScrapeCommittees:
    """Tests for scrape_committees function."""

    @pytest.mark.parametrize(
        ("html", "expected"),
        [
            (
                """
                <span class="font_weight_m">Committee(s):</span>
                <span class="text_right">
                    <br>
                    <span>Criminal Justice and Public Safety</span>
                    <br>
                </span>
                """,
                "Criminal Justice and Public Safety",
            ),
            (
                """
                <span class="font_weight_m">Committee(s):</span>
                <span class="text_right">
                    <br>
                    <span>Criminal Justice and Public Safety</span>
                    <br>
                    <span>Government Oversight Committee</span>
                    <br>
                </span>
                """,
                "Criminal Justice and Public Safety; Government Oversight Committee",
            ),
            (
                """
                <span class="font_weight_m">Committee(s):</span>
                <span class="text_right">
                    <br>
                    <span>Agriculture, Conservation and Forestry</span>
                    <br>
                    <span><i class="fas fa-check"></i> Marine Resources - Chair</span>
                    <br>
                    <span>Energy, Utilities and Technology</span>
                    <br>
                </span>
                """,
                "Agriculture, Conservation and Forestry; Marine Resources - Chair; Energy, Utilities and Technology",
            ),
            (
                "<span class='font_weight_m'>Other Label:</span>",
                "",
            ),
            ("", ""),
        ],
        ids=["single_committee", "two_committees", "three_committees_with_chair", "no_committees", "empty_html"],
    )
    def test_committee_extraction(self, html: str, expected: str) -> None:
        """Test extraction of committee information."""
        soup = BeautifulSoup(html, "html.parser")
        spans = soup.find_all("span", class_="font_weight_m")

        result = scrape_committees(spans)
        assert result == expected


class TestScrapeDetailedLegislatorInfo:
    """Tests for scrape_detailed_legislator_info function."""

    def test_complete_info(self, mock_http_response: Mock) -> None:
        """Test extraction of complete legislator information."""
        html = """
        <div class="column-two-two-third column-last drop-shadow curved" id="main-info">
            <div class="member-name">Chad R. Perkins</div>
            <div class="member-info">State Representative</div>
            <div class="member-info">(R-Dover-Foxcroft)</div>
            <p>
                <a href="mailto:Chad.Perkins@legislature.maine.gov"><i class="fas fa-envelope"></i> Chad.Perkins@legislature.maine.gov</a>
                <br>
                2 State House Station, Augusta, ME 04333
                <br>
                <span class="font_weight_m">Contact:</span>
                <span class="text_right">(207) 279-0927</span>
                <br>
                <span class="font_weight_m">Committee(s):</span>
                <span class="text_right">
                    <br>
                    <span>Criminal Justice and Public Safety</span>
                    <br>
                    <span>Government Oversight Committee</span>
                    <br>
                </span>
            </p>
        </div>
        """

        http = mock_http_response(html)
        email, phone, committees = scrape_detailed_legislator_info(http, "leg.maine.gov", "/member/123", "Chad R. Perkins")

        assert email == "Chad.Perkins@legislature.maine.gov"
        assert phone == "(207) 279-0927"
        assert committees == "Criminal Justice and Public Safety; Government Oversight Committee"

    def test_committee_with_chair_designation(self, mock_http_response: Mock) -> None:
        """Test extraction with committee chair designation."""
        html = """
        <div id="main-info">
        <p>
            <a href="mailto:Allison.Hepler@legislature.maine.gov">Allison.Hepler@legislature.maine.gov</a>
            <br>
            <span class="font_weight_m">Contact:</span>
            <span class="text_right">(207) 319-4396</span>
            <br>
            <span class="font_weight_m">Committee(s):</span>
            <span class="text_right">
                <br>
                <span>Agriculture, Conservation and Forestry</span>
                <br>
                <span><i class="fas fa-check"></i> Marine Resources - Chair</span>
                <br>
            </span>
        </p>
        </div>
        """

        http = mock_http_response(html)
        email, phone, committees = scrape_detailed_legislator_info(http, "leg.maine.gov", "/member/456", "Allison Hepler")

        assert email == "Allison.Hepler@legislature.maine.gov"
        assert phone == "(207) 319-4396"
        assert committees == "Agriculture, Conservation and Forestry; Marine Resources - Chair"

    @pytest.mark.parametrize(
        ("html", "expected_email", "expected_phone", "expected_log"),
        [
            (
                """
                <div id="main-info">
                    <p>
                        2 State House Station, Augusta, ME 04333
                        <br>
                        <span class="font_weight_m">Contact:</span>
                        <span class="text_right">(207) 555-1234</span>
                        <br>
                        <span class="font_weight_m">Committee(s):</span>
                        <span class="text_right">
                            <br>
                            <span>Finance</span>
                            <br>
                        </span>
                    </p>
                </div>
                """,
                "",
                "(207) 555-1234",
                "Email not found for John Smith",
            ),
            (
                """
                <div id="main-info">
                    <p>
                        <a href="mailto:john.smith@legislature.maine.gov">john.smith@legislature.maine.gov</a>
                        <br>
                        2 State House Station, Augusta, ME 04333
                        <br>
                        <span class="font_weight_m">Committee(s):</span>
                        <span class="text_right">
                            <br>
                            <span>Finance</span>
                            <br>
                        </span>
                    </p>
                </div>
                """,
                "john.smith@legislature.maine.gov",
                "",
                "Phone not found for John Smith",
            ),
        ],
        ids=["missing_email", "missing_phone"],
    )
    def test_missing_info_with_warning(  # noqa: PLR0913
        self,
        mock_http_response: Mock,
        caplog: pytest.LogCaptureFixture,
        html: str,
        expected_email: str,
        expected_phone: str,
        expected_log: str,
    ) -> None:
        """Test handles missing information with appropriate warnings."""
        http = mock_http_response(html)
        email, phone, _committees = scrape_detailed_legislator_info(http, "leg.maine.gov", "/member/123", "John Smith")

        assert email == expected_email
        assert phone == expected_phone
        assert expected_log in caplog.text

    def test_missing_main_info_div(self, mock_http_response: Mock) -> None:
        """Test returns empty strings when main-info div missing."""
        html = "<div>No main info</div>"

        http = mock_http_response(html)
        email, phone, committees = scrape_detailed_legislator_info(http, "leg.maine.gov", "/member/123", "John Smith")

        assert email == ""
        assert phone == ""
        assert committees == ""


class TestCollectMunicipalityData:
    """Tests for collect_municipality_data function."""

    def test_collect_multiple_rows(self, mock_http_response: Mock, mock_house_url: Mock) -> None:  # noqa: ARG002
        """Test collecting data from multiple table rows."""
        html = """
        <table class="short-table white">
            <tr>
                <th colspan="3">
                    <h2>Currently Viewing</h2>
                    <h1>R</h1>
                </th>
            </tr>
            <tr>
                <th>Town - District - Member</th>
                <th>Member Profile</th>
            </tr>
            <tr>
                <td class="short-tabletdlf">
                    <b>Randolph</b> - District 53 - Michael H. Lemelin (R - Chelsea)
                </td>
                <td>
                    <a href="/house/house/MemberProfiles/Details/1428" class="btn btn-default">
                        <i class="fas fa-user"></i> View
                    </a>
                </td>
            </tr>
            <tr>
                <td class="short-tabletdlf">
                    <b>Raymond</b> - District 86 - Rolf A. Olsen (R - Raymond)
                </td>
                <td>
                    <a href="/house/house/MemberProfiles/Details/3128" class="btn btn-default">
                        <i class="fas fa-user"></i> View
                    </a>
                </td>
            </tr>
            <tr>
                <td class="short-tabletdlf">
                    <b>Readfield</b> - District 57 - Tavis Rock Hasenfus (D - Readfield)
                </td>
                <td>
                    <a href="/house/house/MemberProfiles/Details/1427" class="btn btn-default">
                        <i class="fas fa-user"></i> View
                    </a>
                </td>
            </tr>
        </table>
        """

        http = mock_http_response(html)
        result = collect_municipality_data(http, "R")

        assert len(result) == 3
        assert result[0] == ("53", "Randolph", "Michael H. Lemelin", "R - Chelsea", "/house/house/MemberProfiles/Details/1428")
        assert result[1] == ("86", "Raymond", "Rolf A. Olsen", "R - Raymond", "/house/house/MemberProfiles/Details/3128")
        assert result[2] == ("57", "Readfield", "Tavis Rock Hasenfus", "D - Readfield", "/house/house/MemberProfiles/Details/1427")

    def test_plantation_prefix(self, mock_http_response: Mock, mock_house_url: Mock) -> None:  # noqa: ARG002
        """Test handles 'plantation' prefix in town names."""
        html = """
        <table class="short-table white">
            <tr><th>Header 1</th></tr>
            <tr><th>Header 2</th></tr>
            <tr>
                <td class="short-tabletdlf">
                    plantation <b>Rangeley</b> - District 73 - Michael Soboleski (R - Phillips)
                </td>
                <td>
                    <a href="/house/house/MemberProfiles/Details/1482" class="btn btn-default">View</a>
                </td>
            </tr>
        </table>
        """

        http = mock_http_response(html)
        result = collect_municipality_data(http, "R")

        assert len(result) == 1
        assert result[0][1] == "plantation Rangeley"  # Town includes the plantation prefix

    @pytest.mark.parametrize(
        ("html", "expected_length", "expected_detail_url"),
        [
            ("<div>No table here</div>", 0, None),
            (
                """
                <table class="short-table white">
                    <tr><th>Header 1</th></tr>
                    <tr><th>Header 2</th></tr>
                    <tr>
                        <td class="short-tabletdlf">Manchester - District 23 - John Smith (Democrat)</td>
                    </tr>
                </table>
                """,
                1,
                "",
            ),
        ],
        ids=["no_table", "missing_link"],
    )
    def test_edge_cases(
        self,
        mock_http_response: Mock,
        mock_house_url: Mock,  # noqa: ARG002
        html: str,
        expected_length: int,
        expected_detail_url: str | None,
    ) -> None:
        """Test edge cases in municipality data collection."""
        http = mock_http_response(html)
        result = collect_municipality_data(http, "A")

        assert len(result) == expected_length
        if expected_detail_url is not None:
            assert result[0][4] == expected_detail_url


class TestGetMostCommonUrl:
    """Tests for get_most_common_url function."""

    @pytest.mark.parametrize(
        ("urls", "expected"),
        [
            (["/member/123"], "/member/123"),
            (["/member/123", "/member/456", "/member/123", "/member/123", "/member/456"], "/member/123"),
            (["/house/house/MemberProfiles/Details/1428"], "/house/house/MemberProfiles/Details/1428"),
            ([], ""),
        ],
        ids=["single_url", "most_common_url", "realistic_url_path", "empty_list"],
    )
    def test_url_frequency(self, urls: list[str], expected: str) -> None:
        """Test URL frequency counting."""
        result = get_most_common_url(urls)
        if expected:
            assert result == expected
        else:
            assert result == ""

    def test_tie_returns_valid_url(self) -> None:
        """Test returns valid URL when URLs tied in frequency."""
        urls = ["/member/123", "/member/456"]
        result = get_most_common_url(urls)
        assert result in urls


class TestGetPagination:
    """Tests for get_pagination function."""

    def test_pagination_extraction(self, mock_http_response: Mock, mock_house_url: Mock) -> None:  # noqa: ARG002
        """Test pagination letter extraction structure."""
        html = """
        <div class="pagination">
            <ul class="pagination">
                <li class="active">
                    <span><a href="?selectedLetter=A">A</a></span>
                </li>
                <li class="active">
                    <span><a href="?selectedLetter=B">B</a></span>
                </li>
                <li class="active">
                    <span><a href="?selectedLetter=C">C</a></span>
                </li>
                <li class="inactive">
                    <span>Q</span>
                </li>
                <li class="active">
                    <span><a href="?selectedLetter=R">R</a></span>
                </li>
            </ul>
        </div>
        """

        http = mock_http_response(html)
        result = get_pagination(http)

        assert "A" in result
        assert "B" in result
        assert "C" in result
        assert "R" in result
