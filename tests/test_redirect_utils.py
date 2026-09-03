import redirect_utils


def test_safe_local_path_with_query_and_fragment_is_preserved():
    assert (
        redirect_utils.safe_redirect_path("/planning?tab=demand#planning-section-2001")
        == "/planning?tab=demand#planning-section-2001"
    )


def test_bare_fragment_only_path_is_preserved():
    assert (
        redirect_utils.safe_redirect_path("/planning#planning-section-2001")
        == "/planning#planning-section-2001"
    )


def test_external_absolute_url_is_rejected():
    assert redirect_utils.safe_redirect_path("http://evil.example.com/x") == "/dashboard"
    assert redirect_utils.safe_redirect_path("https://evil.example.com/x") == "/dashboard"


def test_protocol_relative_url_is_rejected():
    assert redirect_utils.safe_redirect_path("//evil.example.com/x") == "/dashboard"


def test_missing_or_blank_path_falls_back_to_default():
    assert redirect_utils.safe_redirect_path("") == "/dashboard"
    assert redirect_utils.safe_redirect_path(None) == "/dashboard"


def test_custom_default_is_honored_for_unsafe_or_missing_values():
    assert redirect_utils.safe_redirect_path("", default="/planning") == "/planning"
    assert redirect_utils.safe_redirect_path("http://evil.example.com", default="/planning") == "/planning"
    assert redirect_utils.safe_redirect_path("//evil.example.com", default="/planning") == "/planning"


def test_redirect_with_notice_preserves_fragment_after_injected_query_param():
    response = redirect_utils.redirect_with_notice(
        "/planning#planning-section-2001", "Saved.",
    )
    assert response.headers["location"] == "/planning?notice=Saved.#planning-section-2001"


def test_redirect_with_error_preserves_fragment_and_existing_query():
    response = redirect_utils.redirect_with_error(
        "/planning?tab=demand#planning-section-2001", "Blocked.",
    )
    assert response.headers["location"] == "/planning?tab=demand&error=Blocked.#planning-section-2001"


def test_redirect_with_notice_falls_back_to_default_for_unsafe_path():
    response = redirect_utils.redirect_with_notice("http://evil.example.com", "x")
    assert response.headers["location"].startswith("/dashboard?notice=")
