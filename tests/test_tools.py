import pytest

from portfolio_agent.metadata import EntityLinker, SchemaCatalog
from portfolio_agent.tools import AmbiguousPortfolio, Tools


@pytest.fixture(scope="module")
def catalog(settings):
    return SchemaCatalog(settings.db_path)


@pytest.fixture(scope="module")
def linker(catalog):
    return EntityLinker(catalog.portfolio_names, catalog.sector_names)


@pytest.fixture(scope="module")
def tools(settings, linker):
    return Tools(settings, linker)


def by_sector(result):
    return {e.sector: e for e in result.exposures}


def test_single_sector_fund(tools):
    result = tools.exposure_calculator("Tech Innovation Fund")
    assert by_sector(result)["Technology"].exposure_pct == 100
    assert len(result.exposures) == 1


def test_known_values_for_international_equity(tools):
    sectors = by_sector(tools.exposure_calculator("International Equity Fund"))
    assert {k: v.exposure_pct for k, v in sectors.items()} == {
        "Energy": 38,
        "Technology": 36,
        "Automotive": 15,
        "Consumer Staples": 11,
    }


def test_mixed_fund_excludes_bonds_and_renormalises(tools):
    result = tools.exposure_calculator("Conservative Income Fund")
    assert result.bonds_excluded == 4
    assert sum(e.exposure_pct for e in result.exposures) == pytest.approx(100, abs=0.01)
    assert sum(e.portfolio_weight_pct for e in result.exposures) == pytest.approx(32, abs=0.01)
    assert any("excluded" in w for w in result.warnings)


def test_weights_not_summing_to_one_are_flagged(tools):
    result = tools.exposure_calculator("Total Stock Market Index Fund")
    assert sum(e.exposure_pct for e in result.exposures) == pytest.approx(100, abs=0.01)
    assert any("98.00%" in w for w in result.warnings)


@pytest.mark.parametrize("name", ["Fixed Income Plus", "Total Bond Market Index Fund"])
def test_bond_only_fund_does_not_divide_by_zero(tools, name):
    result = tools.exposure_calculator(name)
    assert result.exposures == [] and "no equities" in result.warnings[0]


def test_ambiguous_and_unknown_names_raise(tools):
    with pytest.raises(AmbiguousPortfolio) as ambiguous:
        tools.exposure_calculator("international")
    assert set(ambiguous.value.candidates) == {"International Equity Fund", "Total International Index Fund"}
    with pytest.raises(AmbiguousPortfolio) as unknown:
        tools.exposure_calculator("Zebra Holdings")
    assert unknown.value.candidates == []


def test_injection_in_portfolio_name_is_harmless(tools):
    with pytest.raises(AmbiguousPortfolio):
        tools.exposure_calculator("x'; DROP TABLE holdings; --")


@pytest.mark.parametrize(
    "question,expected",
    [
        ("exposure for international equity", ["International Equity Fund"]),
        ("the Tech Innovation Fund", ["Tech Innovation Fund"]),
        ("tech innovaton fund", ["Tech Innovation Fund"]),
        ("Total International Index Fund", ["Total International Index Fund"]),
        ("how many portfolios are there", []),
    ],
)
def test_linker_confident_matches(linker, question, expected):
    assert linker.link(question).portfolios == expected


def test_portfolio_name_is_not_read_as_a_sector(linker):
    assert linker.link("Tech Innovation Fund exposure").sectors == []
    assert linker.link("tech stocks").sectors == ["Technology"]


@pytest.mark.parametrize(
    "question,expected",
    [
        ("What was Apple's closing price?", "AAPL (Apple Inc.)"),
        ("Which portfolios hold NVDA?", "NVDA (NVIDIA Corporation)"),
        ("Is Microsoft held anywhere?", "MSFT (Microsoft Corporation)"),
    ],
)
def test_linker_finds_securities(catalog, question, expected):
    linker = EntityLinker(catalog.portfolio_names, catalog.sector_names, catalog.securities)
    assert expected in linker.link(question).securities


def test_catalog_keeps_free_text_out_of_prompts(catalog):
    assert "Initial purchase" not in catalog.render()
    assert "status TEXT in {Active, Passive}" in catalog.render()


