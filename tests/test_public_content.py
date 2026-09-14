"""Public website content endpoints.

The spec treats "no code changes to update content" as an architectural
constraint, so these tests assert that pages are assembled from the database
and that unpublished or unverified material never reaches the public site.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.content import (
    ContentBlock,
    LegalPage,
    Qualification,
    TeamMember,
    Testimonial,
)


def test_home_returns_seeded_hero(api: TestClient) -> None:
    body = api.get("/api/v1/public/home").json()
    assert body["hero"]["title"] == "Professional UK Tax & Compliance Advisory"
    assert len(body["key_strengths"]) == 7


def test_home_service_teasers_come_from_the_taxonomy(api: TestClient) -> None:
    body = api.get("/api/v1/public/home?service_limit=6").json()
    slugs = [s["slug"] for s in body["services"]]
    assert slugs[:3] == ["personal-tax", "limited-company-accounting", "bookkeeping"]
    assert len(slugs) == 6


def test_home_teasers_scoped_to_a_market_only_offer_what_it_provides(
    api: TestClient,
) -> None:
    """The homepage links each teaser into the selected market.

    CIS is a UK construction scheme and is not offered in India, so an unscoped
    teaser list would put a card on the homepage whose link 404s.
    """
    everywhere = api.get("/api/v1/public/home?service_limit=24").json()
    assert "cis-services" in {s["slug"] for s in everywhere["services"]}

    india = api.get("/api/v1/public/home?service_limit=24&region=india").json()
    india_slugs = {s["slug"] for s in india["services"]}
    assert "cis-services" not in india_slugs

    offered = api.get("/api/v1/public/regions/india/services").json()
    assert india_slugs == {s["slug"] for s in offered["services"]}


@pytest.mark.parametrize("region", ["atlantis", ""])
def test_home_falls_back_to_every_service_for_an_unusable_market(
    api: TestClient, region: str
) -> None:
    """The slug arrives from a cookie the visitor controls, and a market can be
    unpublished at any time — neither should break the homepage."""
    body = api.get(f"/api/v1/public/home?service_limit=24&region={region}").json()
    assert "cis-services" in {s["slug"] for s in body["services"]}


def test_the_hero_names_the_chosen_market(api: TestClient) -> None:
    """One editable string, not a row per market."""
    titles = {}
    for slug in ("uk", "india", "uae", "oman"):
        body = api.get(f"/api/v1/public/home?region={slug}").json()
        titles[slug] = body["hero"]["title"]

    assert titles["uk"] == "Professional UK Tax & Compliance Advisory"
    assert titles["india"] == "Professional India Tax & Compliance Advisory"
    assert titles["uae"] == "Professional UAE Tax & Compliance Advisory"
    assert titles["oman"] == "Professional Oman Tax & Compliance Advisory"
    # The token itself never reaches a visitor.
    assert not any("{region}" in t for t in titles.values())


@pytest.mark.parametrize("query", ["", "?region=atlantis"])
def test_the_hero_falls_back_to_the_primary_market(api: TestClient, query: str) -> None:
    """The slug arrives from a cookie the visitor controls, and a market can be
    unpublished at any time — neither should leave a token on the page."""
    body = api.get(f"/api/v1/public/home{query}").json()
    assert body["hero"]["title"] == "Professional UK Tax & Compliance Advisory"


def test_renaming_a_market_renames_the_heading(
    api: TestClient, db: Session
) -> None:
    from app.models.service import Region

    region = db.execute(select(Region).where(Region.slug == "india")).scalar_one()
    region.short_name = "Bhārat"
    db.flush()

    body = api.get("/api/v1/public/home?region=india").json()
    assert body["hero"]["title"] == "Professional Bhārat Tax & Compliance Advisory"


def test_a_market_without_a_short_name_uses_its_full_one(
    api: TestClient, db: Session
) -> None:
    from app.models.service import Region

    region = db.execute(select(Region).where(Region.slug == "uk")).scalar_one()
    region.short_name = None
    db.flush()

    body = api.get("/api/v1/public/home?region=uk").json()
    assert body["hero"]["title"] == "Professional United Kingdom Tax & Compliance Advisory"


def test_a_stray_brace_in_admin_copy_does_not_break_the_page(
    api: TestClient, db: Session
) -> None:
    """The substitution is a replacement, not a format string. `str.format`
    would turn a typo in the Admin Portal into a 500 on the homepage."""
    block = db.execute(
        select(ContentBlock).where(ContentBlock.key == "home_hero")
    ).scalar_one()
    block.title = "Professional {region} Tax {and} Compliance {"
    db.flush()

    response = api.get("/api/v1/public/home?region=uk")
    assert response.status_code == 200
    assert response.json()["hero"]["title"] == "Professional UK Tax {and} Compliance {"


def test_dropping_the_token_makes_the_heading_the_same_everywhere(
    api: TestClient, db: Session
) -> None:
    block = db.execute(
        select(ContentBlock).where(ContentBlock.key == "home_hero")
    ).scalar_one()
    block.title = "Tax and compliance, handled"
    db.flush()

    for slug in ("uk", "india"):
        body = api.get(f"/api/v1/public/home?region={slug}").json()
        assert body["hero"]["title"] == "Tax and compliance, handled"


def test_home_carries_the_core_values(api: TestClient) -> None:
    """Shown on the homepage as well as About, from the one set of rows."""
    home = api.get("/api/v1/public/home").json()
    about = api.get("/api/v1/public/about").json()
    assert [v["title"] for v in home["core_values"]] == [
        v["title"] for v in about["core_values"]
    ]
    assert len(home["core_values"]) == 6


def test_about_assembles_every_section(api: TestClient) -> None:
    body = api.get("/api/v1/public/about").json()

    assert "Established in 2016" in body["intro"]["body"]
    assert body["vision"]["title"] == "Our Vision"
    assert len(body["core_values"]) == 6
    assert len(body["key_strengths"]) == 7
    assert len(body["milestones"]) == 3


def test_bullet_lists_are_attached_to_their_block(api: TestClient) -> None:
    body = api.get("/api/v1/public/about").json()
    assert len(body["mission"]["items"]) == 7
    assert body["mission"]["items"][0].startswith("Deliver reliable UK tax")
    assert len(body["why_choose_us"]["items"]) == 7


def test_unverified_content_is_absent_until_smartaware_supplies_it(
    api: TestClient,
) -> None:
    """Seeded empty on purpose — these are factual claims about a real firm."""
    body = api.get("/api/v1/public/about").json()
    assert body["team"] == []
    assert body["qualifications"] == []
    assert body["achievements"] == []
    # Testimonials are the exception: they ship as placeholders so the carousel
    # can be seen, and every one says so. See test_seeds.
    assert all(t["source"] == "placeholder" for t in body["testimonials"])


def test_editing_a_block_changes_the_public_page(api: TestClient, db: Session) -> None:
    """The whole point of the content being database-driven."""
    block = db.execute(select(ContentBlock).where(ContentBlock.key == "vision")).scalar_one()
    block.body = "A completely new vision statement."
    db.flush()

    body = api.get("/api/v1/public/about").json()
    assert body["vision"]["body"] == "A completely new vision statement."


def test_unpublished_block_is_withheld(api: TestClient, db: Session) -> None:
    block = db.execute(select(ContentBlock).where(ContentBlock.key == "vision")).scalar_one()
    block.is_published = False
    db.flush()

    assert api.get("/api/v1/public/about").json()["vision"] is None


def test_unpublished_team_member_is_not_shown(api: TestClient, db: Session) -> None:
    db.add(TeamMember(name="Draft Person", is_published=False))
    db.flush()
    assert api.get("/api/v1/public/about").json()["team"] == []


def test_published_but_unverified_qualification_is_withheld(api: TestClient, db: Session) -> None:
    """Publishing alone is not enough: the content brief permits only verified
    credentials on the public site, so both flags must be set."""
    db.add(Qualification(name="Some Membership", is_published=True, is_verified=False))
    db.flush()
    assert api.get("/api/v1/public/about").json()["qualifications"] == []

    row = db.execute(select(Qualification)).scalars().first()
    row.is_verified = True
    db.flush()

    names = [q["name"] for q in api.get("/api/v1/public/about").json()["qualifications"]]
    assert names == ["Some Membership"]


def test_ordering_follows_sort_order(api: TestClient, db: Session) -> None:
    # Sorted after the seeded placeholders, so this asserts ordering rather
    # than an empty table.
    db.add_all(
        [
            Testimonial(author_name="Second", quote="b", is_published=True, sort_order=91),
            Testimonial(author_name="First", quote="a", is_published=True, sort_order=90),
        ]
    )
    db.flush()
    names = [t["author_name"] for t in api.get("/api/v1/public/home").json()["testimonials"]]
    assert names[-2:] == ["First", "Second"]


# --- Contact ------------------------------------------------------------------


def test_contact_details_are_withheld_until_supplied(api: TestClient) -> None:
    """Seeded as unpublished placeholders, so the page cannot show an invented
    address as though it were real."""
    body = api.get("/api/v1/public/contact").json()
    assert body["details"] == []
    assert body["social_links"] == []


def test_publishing_a_contact_detail_surfaces_it(api: TestClient, db: Session) -> None:
    from app.models.content import ContactDetail

    row = db.execute(select(ContactDetail).where(ContactDetail.detail_type == "email")).scalar_one()
    row.value = "hello@smartaware.example"
    row.is_published = True
    db.flush()

    details = api.get("/api/v1/public/contact").json()["details"]
    assert [d["value"] for d in details] == ["hello@smartaware.example"]


# --- Legal --------------------------------------------------------------------


def test_unpublished_legal_pages_are_not_listed(api: TestClient) -> None:
    assert api.get("/api/v1/public/legal").json() == []


def test_draft_legal_page_cannot_be_read_by_guessing_its_slug(
    api: TestClient,
) -> None:
    """A draft privacy policy must not be readable just because its URL is
    predictable, so unpublished is indistinguishable from missing."""
    assert api.get("/api/v1/public/legal/privacy-policy").status_code == 404


def test_publishing_a_legal_page_makes_it_readable(api: TestClient, db: Session) -> None:
    page = db.execute(select(LegalPage).where(LegalPage.slug == "privacy-policy")).scalar_one()
    page.body = "Our actual privacy policy."
    page.is_published = True
    db.flush()

    assert [p["slug"] for p in api.get("/api/v1/public/legal").json()] == ["privacy-policy"]
    assert api.get("/api/v1/public/legal/privacy-policy").json()["body"] == (
        "Our actual privacy policy."
    )


def test_unknown_content_key_is_404(api: TestClient) -> None:
    assert api.get("/api/v1/public/content/does-not-exist").status_code == 404


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/public/home",
        "/api/v1/public/about",
        "/api/v1/public/contact",
        "/api/v1/public/legal",
    ],
)
def test_public_endpoints_need_no_authentication(api: TestClient, path: str) -> None:
    assert api.get(path).status_code == 200
