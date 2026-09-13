"""Password hashing and token handling primitives."""

from app.core.security import (
    generate_client_ref,
    generate_token,
    hash_password,
    hash_token,
    verify_password,
)


def test_password_round_trip() -> None:
    hashed = hash_password("correct horse battery staple")
    assert hashed != "correct horse battery staple"
    assert verify_password("correct horse battery staple", hashed)
    assert not verify_password("wrong password", hashed)


def test_hashes_are_salted() -> None:
    assert hash_password("same") != hash_password("same")


def test_verify_rejects_malformed_hash() -> None:
    assert not verify_password("anything", "not-a-valid-hash")


def test_invite_tokens_are_stored_hashed() -> None:
    """Only the hash is persisted, so a database disclosure cannot be replayed
    into account creation."""
    token = generate_token()
    stored = hash_token(token)
    assert stored != token
    assert hash_token(token) == stored, "lookup must be deterministic"
    assert hash_token(generate_token()) != stored


def test_client_refs_are_unique_and_not_derived_from_identifiers() -> None:
    refs = {generate_client_ref() for _ in range(500)}
    assert len(refs) == 500
    assert all(r.startswith("SA-") for r in refs)
