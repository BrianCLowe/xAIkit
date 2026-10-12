"""Authorize URL query merge (offline). Real build_oauth_authorize_url."""

from __future__ import annotations

from urllib.parse import parse_qsl, urlsplit

import pytest

from xaikit import build_oauth_authorize_url

# Captured from build_oauth_authorize_url before the query merge.
# No-query and trailing-"?" inputs both returned this exact string.
_EXACT_NO_QUERY = (
    "https://idp.example/authorize?client_id=fake-client"
    "&redirect_uri=https%3A%2F%2Fapp.example%2Fcb"
    "&response_type=code&scope=openid&state=s1"
)

_KIT_PAIRS = [
    ("client_id", "fake-client"),
    ("redirect_uri", "https://app.example/cb"),
    ("response_type", "code"),
    ("scope", "openid"),
    ("state", "s1"),
]


def _authorize(authorize_url: str, **kwargs: str) -> str:
    params: dict[str, str] = {
        "client_id": "fake-client",
        "redirect_uri": "https://app.example/cb",
        "state": "s1",
        "authorize_url": authorize_url,
    }
    params.update(kwargs)
    return build_oauth_authorize_url(**params)


def _split_pairs(url: str):
    """urlsplit plus parse_qsl as a list so duplicate names stay visible."""
    parts = urlsplit(url)
    pairs = parse_qsl(parts.query, keep_blank_values=True)
    return parts, pairs


def test_xk_ac_oauth_1_keeps_existing_query_and_order() -> None:
    url = _authorize("https://idp.example/authorize?audience=api")
    assert url.count("?") == 1
    parts, pairs = _split_pairs(url)
    assert parts.scheme == "https"
    assert parts.netloc == "idp.example"
    assert parts.path == "/authorize"
    assert pairs == [("audience", "api"), *_KIT_PAIRS]
    names = [name for name, _value in pairs]
    assert len(names) == len(set(names))


def test_xk_ac_oauth_1_encoded_caller_value_keeps_relative_order() -> None:
    url = _authorize(
        "https://idp.example/authorize?prompt=login%20consent&audience=api&foo=bar"
    )
    assert url.count("?") == 1
    _parts, pairs = _split_pairs(url)
    assert pairs == [
        ("prompt", "login consent"),
        ("audience", "api"),
        ("foo", "bar"),
        *_KIT_PAIRS,
    ]
    assert "prompt=login+consent" in url


def test_xk_ac_oauth_2_kit_values_replace_caller_conflicts() -> None:
    url = _authorize(
        "https://idp.example/authorize"
        "?client_id=caller-evil&scope=caller-scope&response_type=token&audience=api"
    )
    assert url.count("?") == 1
    _parts, pairs = _split_pairs(url)
    names = [name for name, _value in pairs]
    assert names.count("client_id") == 1
    assert names.count("scope") == 1
    assert names.count("response_type") == 1
    assert pairs == [("audience", "api"), *_KIT_PAIRS]
    assert "caller-evil" not in url
    assert "caller-scope" not in url
    assert "response_type=token" not in url
    assert "token" not in [value for _name, value in pairs]


def test_xk_ac_oauth_2_only_client_id_conflict() -> None:
    url = _authorize("https://idp.example/authorize?client_id=caller-evil")
    assert url.count("?") == 1
    _parts, pairs = _split_pairs(url)
    names = [name for name, _value in pairs]
    assert names.count("client_id") == 1
    assert pairs == _KIT_PAIRS
    assert "caller-evil" not in url


def test_xk_ac_oauth_2_repeated_caller_scope_collapses() -> None:
    url = _authorize("https://idp.example/authorize?scope=a&scope=b")
    assert url.count("?") == 1
    _parts, pairs = _split_pairs(url)
    names = [name for name, _value in pairs]
    assert names.count("scope") == 1
    assert pairs == _KIT_PAIRS
    assert "scope=a" not in url
    assert "scope=b" not in url


def test_xk_ac_oauth_2_redirect_uri_and_state_use_kit_values() -> None:
    url = _authorize(
        "https://idp.example/authorize"
        "?redirect_uri=https%3A%2F%2Fevil.example%2Fcb&state=caller-state&audience=api"
    )
    assert url.count("?") == 1
    _parts, pairs = _split_pairs(url)
    names = [name for name, _value in pairs]
    assert names.count("redirect_uri") == 1
    assert names.count("state") == 1
    assert pairs == [
        ("audience", "api"),
        ("client_id", "fake-client"),
        ("redirect_uri", "https://app.example/cb"),
        ("response_type", "code"),
        ("scope", "openid"),
        ("state", "s1"),
    ]
    assert "evil.example" not in url
    assert "caller-state" not in url


def test_xk_ac_oauth_2_scopes_argument_wins_over_caller_scope() -> None:
    url = _authorize(
        "https://idp.example/authorize?scope=caller-scope&audience=api",
        scopes="email",
    )
    assert url.count("?") == 1
    _parts, pairs = _split_pairs(url)
    names = [name for name, _value in pairs]
    assert names.count("scope") == 1
    assert pairs == [
        ("audience", "api"),
        ("client_id", "fake-client"),
        ("redirect_uri", "https://app.example/cb"),
        ("response_type", "code"),
        ("scope", "email"),
        ("state", "s1"),
    ]
    assert "caller-scope" not in url


def test_xk_ac_oauth_3_no_query_and_trailing_question_marks_match_legacy() -> None:
    for authorize_url in (
        "https://idp.example/authorize",
        "https://idp.example/authorize?",
        "https://idp.example/authorize??",
    ):
        url = _authorize(authorize_url)
        assert url == _EXACT_NO_QUERY
        assert url.count("?") == 1


def test_fragment_stays_after_merged_query() -> None:
    url = _authorize("https://idp.example/authorize?audience=api#frag")
    assert url.count("?") == 1
    parts, pairs = _split_pairs(url)
    assert parts.fragment == "frag"
    assert parts.scheme == "https"
    assert parts.netloc == "idp.example"
    assert parts.path == "/authorize"
    assert url.index("?") < url.index("#")
    assert pairs == [("audience", "api"), *_KIT_PAIRS]
    names = [name for name, _value in pairs]
    assert len(names) == len(set(names))


def test_authorize_url_only_question_mark_is_required_error() -> None:
    with pytest.raises(ValueError, match="authorize_url is required"):
        _authorize("?")
