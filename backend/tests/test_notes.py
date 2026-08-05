import pytest
from sqlalchemy.exc import IntegrityError

from app.models import Note, Scan, SitePage, WebResource, WebsiteProperty
from app.schemas.page_workspaces import NoteCreate, NoteUpdate
from app.services.notes import create_note, delete_note, list_notes, update_note


def test_notes_require_one_target_and_support_plain_text_crud(db_session) -> None:
    site, scan, site_page = _targets(db_session)
    with pytest.raises(IntegrityError):
        db_session.add(Note(website_property_id=site.id, scan_id=scan.id, body="invalid"))
        db_session.commit()
    db_session.rollback()

    note = create_note(
        db_session,
        NoteCreate(body="  <script>alert(1)</script>\nSecond line  "),
        site_page_id=site_page.id,
    )
    updated = update_note(
        db_session, note.id, NoteUpdate(body="Updated\nplain text", is_pinned=True)
    )
    listed = list_notes(db_session, site_page_id=site_page.id)

    assert updated is not None and updated.is_pinned is True
    assert listed.items[0].body == "Updated\nplain text"
    assert delete_note(db_session, note.id) == note.id
    assert list_notes(db_session, site_page_id=site_page.id).total == 0


def test_pinned_notes_sort_first_and_targets_remain_isolated(db_session) -> None:
    site, scan, site_page = _targets(db_session)
    create_note(db_session, NoteCreate(body="Site note"), website_property_id=site.id)
    create_note(db_session, NoteCreate(body="Scan note"), scan_id=scan.id)
    create_note(db_session, NoteCreate(body="Page regular"), site_page_id=site_page.id)
    create_note(
        db_session, NoteCreate(body="Page pinned", is_pinned=True), site_page_id=site_page.id
    )

    page_notes = list_notes(db_session, site_page_id=site_page.id)
    assert [note.body for note in page_notes.items] == ["Page pinned", "Page regular"]
    assert list_notes(db_session, website_property_id=site.id).total == 1
    assert list_notes(db_session, scan_id=scan.id).total == 1


def _targets(db_session) -> tuple[WebsiteProperty, Scan, SitePage]:
    site = WebsiteProperty(
        name="Example",
        base_url="https://example.com/",
        normalized_base_url="https://example.com/",
        description=None,
        group_key="Other",
        locale=None,
        platform_key="Other",
        ownership_key="Unknown",
        scope_config={},
        is_active=True,
    )
    resource = WebResource(
        resource_type="page",
        normalized_url="https://example.com/page",
        scheme="https",
        host="example.com",
        port=None,
        path="/page",
        query="",
    )
    db_session.add_all([site, resource])
    db_session.flush()
    scan = Scan(
        website_property_id=site.id,
        starting_url=site.base_url,
        status="completed",
        scope_config={},
    )
    site_page = SitePage(website_property_id=site.id, resource_id=resource.id)
    db_session.add_all([scan, site_page])
    db_session.commit()
    return site, scan, site_page
