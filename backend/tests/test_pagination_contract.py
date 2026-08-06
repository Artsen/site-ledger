from app.main import app


def test_major_catalog_endpoints_enforce_250_row_maximum() -> None:
    schema = app.openapi()
    for path in ["/api/sites", "/api/scans/history", "/api/sites/{site_id}/pages"]:
        parameters = schema["paths"][path]["get"]["parameters"]
        limit = next(parameter for parameter in parameters if parameter["name"] == "limit")
        assert limit["schema"]["minimum"] == 1
        assert limit["schema"]["maximum"] == 250
