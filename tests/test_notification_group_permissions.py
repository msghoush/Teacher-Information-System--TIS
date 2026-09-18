"""Action-level permission regression for grouped notification operations."""

import os
from types import SimpleNamespace

import pytest
from fastapi.responses import JSONResponse
from starlette.requests import Request

os.environ["TIS_SESSION_SECRET"] = "notification-group-permission-test-secret-long-enough"

import main


PERMISSIONS = {
    "read": "notifications.mark_read",
    "done": "notifications.resolve",
    "archive": "notifications.archive",
}


def _request():
    return Request({
        "type": "http", "http_version": "1.1", "method": "POST",
        "path": "/notifications/group-action", "raw_path": b"/notifications/group-action",
        "query_string": b"", "headers": [(b"host", b"testserver")],
        "scheme": "http", "server": ("testserver", 80),
        "client": ("testclient", 50000), "root_path": "", "app": main.app,
    })


class _Db:
    def __init__(self):
        self.commits = 0

    def commit(self):
        self.commits += 1


@pytest.mark.parametrize("granted_action", PERMISSIONS)
@pytest.mark.parametrize("posted_action", PERMISSIONS)
def test_group_action_requires_its_own_permission(monkeypatch, granted_action, posted_action):
    actor = SimpleNamespace(user_id="actor")
    row = SimpleNamespace(
        status=main.NOTIFICATION_STATUS_NEW,
        seen_at=None, resolved_at=None, resolved_by_user_id=None,
        requester_archived_at=None, requester_archived_by_user_id=None,
        recipient_archived_at=None, recipient_archived_by_user_id=None,
    )
    db = _Db()
    monkeypatch.setattr(main.auth, "get_current_user", lambda request, session: actor)
    monkeypatch.setattr(
        main.auth, "has_permission",
        lambda session, user, key: key == PERMISSIONS[granted_action],
    )
    monkeypatch.setattr(
        main.authorization, "build_access_denied_response",
        lambda *args, **kwargs: JSONResponse({"denied": kwargs["permission_keys"]}, status_code=403),
    )
    monkeypatch.setattr(main, "_ensure_system_notifications_table_columns", lambda: None)
    monkeypatch.setattr(
        main, "_base_notification_query_for_box",
        lambda session, user_id, box: SimpleNamespace(all=lambda: [row]),
    )
    monkeypatch.setattr(main, "_notification_group_matches", lambda notification, key: True)

    response = main.update_notification_group(
        _request(), group_key="group", action=posted_action, box="inbox", db=db,
    )
    if granted_action != posted_action:
        assert response.status_code == 403
        assert db.commits == 0
        assert row.status == main.NOTIFICATION_STATUS_NEW
        assert row.seen_at is None
        assert row.resolved_at is None
        assert row.recipient_archived_at is None
    else:
        assert response.status_code == 302
        assert db.commits == 1
        if posted_action == "read":
            assert row.status == main.NOTIFICATION_STATUS_SEEN
            assert row.seen_at is not None
        elif posted_action == "done":
            assert row.status == main.NOTIFICATION_STATUS_RESOLVED
            assert row.resolved_at is not None
        else:
            assert row.recipient_archived_at is not None


def test_group_action_archive_sent_uses_sender_pointer(monkeypatch):
    actor = SimpleNamespace(user_id="actor")
    row = SimpleNamespace(
        status=main.NOTIFICATION_STATUS_NEW,
        requester_archived_at=None, requester_archived_by_user_id=None,
        recipient_archived_at=None, recipient_archived_by_user_id=None,
    )
    db = _Db()
    monkeypatch.setattr(main.auth, "get_current_user", lambda request, session: actor)
    monkeypatch.setattr(main.auth, "has_permission", lambda session, user, key: key == PERMISSIONS["archive"])
    monkeypatch.setattr(main, "_ensure_system_notifications_table_columns", lambda: None)
    monkeypatch.setattr(
        main, "_base_notification_query_for_box",
        lambda session, user_id, box: SimpleNamespace(all=lambda: [row]),
    )
    monkeypatch.setattr(main, "_notification_group_matches", lambda notification, key: True)

    response = main.update_notification_group(
        _request(), group_key="group", action="archive", box="sent", db=db,
    )
    assert response.status_code == 302
    assert db.commits == 1
    assert row.requester_archived_at is not None
    assert row.requester_archived_by_user_id == actor.user_id
    assert row.recipient_archived_at is None
