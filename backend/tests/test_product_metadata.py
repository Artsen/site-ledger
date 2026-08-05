from app.main import create_app
from app.product import API_TITLE, API_VERSION, PRODUCT_DESCRIPTION


def test_fastapi_uses_site_ledger_product_metadata() -> None:
    app = create_app()

    assert app.title == API_TITLE == "Site Ledger API"
    assert app.description == PRODUCT_DESCRIPTION
    assert app.version == API_VERSION

    openapi_info = app.openapi()["info"]
    assert openapi_info["title"] == "Site Ledger API"
    assert openapi_info["description"] == PRODUCT_DESCRIPTION
    assert openapi_info["version"] == API_VERSION
