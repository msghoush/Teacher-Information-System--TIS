"""M11 HTTP shell permission and integration checks against isolated SQLite."""
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.testclient import TestClient
import pytest

from auth import get_current_user
from dependencies import get_db
from routers import talent_ui
from test_talent_org_intelligence_queries import actor, db, permissions


@pytest.fixture
def client(db):
    app = FastAPI()
    app.mount('/static', StaticFiles(directory='static'), name='static')
    app.include_router(talent_ui.router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: actor()
    return TestClient(app)


def test_navigation_and_html_use_actual_shared_shell(db, client):
    permissions(db, 'talent_programs.view')
    response = client.get('/talent')
    assert response.status_code == 200
    assert 'Talent &amp; Potential' in response.text
    assert '/static/js/talent.js' in response.text
    assert '/static/js/talent-program-workspace.js' in response.text
    assert '/static/js/talent-evaluation-workspace.js' in response.text
    assert '/static/js/talent-operations.js' in response.text
    assert '/static/css/talent-program-workspace.css' in response.text
    assert response.headers['cache-control'] == 'no-store'
    assert 'href="/talent/programs"' in response.text
    assert 'href="/talent/reviews"' not in response.text


def test_talent_year_defaults_to_shell_year_and_respects_explicit_authorized_year(db, client):
    import models

    permissions(db, 'talent_programs.view')
    db.add(models.AcademicYear(id=99, school_group_id=1, year_name='2025-2026', is_active=True))
    db.commit()

    defaulted = client.get('/talent/programs')
    assert defaulted.status_code == 200
    assert '<option value="100" selected>2026-2027</option>' in defaulted.text
    assert '<option value="99" selected>' not in defaulted.text

    explicit = client.get('/talent/programs?academic_year_id=99')
    assert explicit.status_code == 200
    source = open('static/js/talent.js', encoding='utf-8').read()
    assert "params.has('academic_year_id')" in source
    assert "year.value=params.get('academic_year_id')" in source


@pytest.mark.parametrize('view', list(talent_ui.VIEWS))
def test_all_authorized_views_render(db, client, view):
    permissions(db, *set(v[1] for v in talent_ui.VIEWS.values()), 'talent_analytics.view_students')
    response = client.get('/talent/' + view)
    assert response.status_code == 200
    assert 'id="tp-config"' in response.text


def test_student_drill_requires_both_permissions(db, client):
    permissions(db, 'talent_analytics.view')
    assert client.get('/talent/students').status_code == 403


def test_program_permission_does_not_open_profile(db, client):
    permissions(db, 'talent_programs.view')
    assert client.get('/talent/learner-profile?student_id=1001').status_code == 403


def test_unknown_view_is_404(client):
    assert client.get('/talent/unknown').status_code == 404


def test_organization_overview_has_no_duplicate_analytics_navigation(db, client):
    """The Owner's real screenshot showed the full Talent navigation followed
    immediately by a second, overlapping Results & Analytics navigation. The
    primary nav must collapse the whole analytics family into one entry point;
    only the dedicated sub-nav may list the individual analytics pages."""
    permissions(db, 'talent_analytics.view', 'talent_analytics.view_students')
    response = client.get('/talent/analytics')
    assert response.status_code == 200
    for href in ('href="/talent/talent-map"', 'href="/talent/portfolio"',
                 'href="/talent/overlap"', 'href="/talent/longitudinal"',
                 'href="/talent/students"'):
        assert response.text.count(href) == 1, f'{href} must appear exactly once, not duplicated across two navs'
    assert 'Results &amp; Analytics</span>' in response.text


def test_branch_scope_never_advertises_organization_only_talent_actions(db, client):
    permissions(db, 'talent_programs.view', 'talent_programs.govern',
                'talent_evaluation_plans.manage',
                'talent_evaluation_plans.govern',
                'talent_assessment_cycles.govern',
                'talent_official_identifications.record')
    client.app.dependency_overrides[get_current_user] = lambda: actor(scope='BRANCH')
    response = client.get('/talent/programs')
    assert response.status_code == 200
    assert '"talent_programs.govern": false' in response.text
    assert '"talent_evaluation_plans.manage": false' in response.text
    assert '"talent_evaluation_plans.govern": false' in response.text
    assert '"talent_assessment_cycles.govern": false' in response.text
    assert '"talent_official_identifications.record": false' in response.text


def test_evaluation_plan_action_permissions_reach_browser_payload(db, client):
    permissions(db, 'talent_evaluation_plans.view',
                'talent_evaluation_plans.manage',
                'talent_evaluation_plans.govern')
    response = client.get('/talent/evaluation-plans')
    assert response.status_code == 200
    # actor() is durably organization-scoped while retaining Branch 10 as the
    # selected/visible working context. A Branch selection must not suppress
    # organization-authorized Evaluation Plan actions.
    assert '"talent_evaluation_plans.manage": true' in response.text
    assert '"talent_evaluation_plans.govern": true' in response.text
    assert '"talent_evaluation_plans.select_period": true' in response.text


def test_authorized_learner_profile_link_redirects_to_canonical_student_profile(db):
    """An authorized `/talent/learner-profile?student_id=...` request (the target of every
    `static/js/talent.js` "Open Learner Profile" link) must 302 to the canonical Student
    Profile's Talent tab, and that target must independently resolve with the real student's
    name - proving no disconnected "Learner Profile" page is ever actually reached for a
    valid, permitted student_id. This full redirect chain was previously unexercised by any
    automated test (the existing `test_all_authorized_views_render` parametrization omits
    `student_id`, and `test_program_permission_does_not_open_profile` only covers the 403
    case), even though the behavior is real and already correct.
    """
    import models
    from fastapi import FastAPI
    from fastapi.staticfiles import StaticFiles
    from fastapi.testclient import TestClient

    from routers import students_ui

    db.add(models.Student(id=1001, school_group_id=1, first_name='Alya', last_name='Learner', status='active'))
    db.commit()
    permissions(db, 'talent_learner_profiles.view', 'students.view')

    app = FastAPI()
    app.mount('/static', StaticFiles(directory='static'), name='static')
    app.include_router(talent_ui.router)
    app.include_router(students_ui.router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: actor()
    combined_client = TestClient(app)

    redirect = combined_client.get('/talent/learner-profile?student_id=1001', follow_redirects=False)
    assert redirect.status_code == 302
    assert redirect.headers['location'] == '/students/1001?section=talent'

    resolved = combined_client.get(redirect.headers['location'], follow_redirects=False)
    assert resolved.status_code == 200
    assert 'Alya' in resolved.text and 'Learner' in resolved.text
    # The resolved page is the canonical Student Profile's Talent tab, not a separate
    # standalone "Learner Profile" page identity.
    assert 'Talent &amp; Potential' in resolved.text


def test_evaluation_plan_is_no_longer_a_standalone_primary_nav_entry(db, client):
    """Evaluation Plan/Period configuration now lives only inside a Program's
    own guided setup (its embedded Step 3/#tp-schedule); it must not remain a
    separate top-level Talent surface in the primary nav or the Overview
    action-card grid (there must be exactly one user-facing entry point)."""
    permissions(db, 'talent_programs.view', 'talent_evaluation_plans.view', 'talent_assessments.view',
                'talent_review_candidates.view', 'talent_analytics.view')
    for view in ('overview', 'programs', 'assessments', 'reviews'):
        response = client.get(f'/talent/{view}')
        assert response.status_code == 200
        assert 'href="/talent/evaluation-plans"' not in response.text
    # The primary nav keeps exactly the operationally-focused five surfaces.
    nav = client.get('/talent/overview').text
    assert 'href="/talent/programs"' in nav
    assert 'href="/talent/assessments"' in nav
    assert 'href="/talent/reviews"' in nav
    assert 'href="/talent/analytics"' in nav


def test_evaluation_plan_deep_link_stays_authorized_under_its_own_permission(db, client):
    """A bookmarked/old Evaluation Plan URL must keep resolving successfully
    under its existing `talent_evaluation_plans.view` gate - the same gate a
    role holding ONLY Evaluation Plan permissions (never talent_programs.view)
    has always used. Merging this deep link into the richer Program-workspace
    experience for a Program-authorized user happens client-side
    (static/js/talent.js), so it never forces an extra server-side
    authorization round-trip against a different permission key that a
    narrower, still-legitimate role would fail."""
    permissions(db, 'talent_evaluation_plans.view')

    with_program = client.get('/talent/evaluation-plans?program_id=7&academic_year_id=100', follow_redirects=False)
    assert with_program.status_code == 200
    assert 'id="tp-config"' in with_program.text

    without_program = client.get('/talent/evaluation-plans', follow_redirects=False)
    assert without_program.status_code == 200
    assert 'id="tp-config"' in without_program.text


def test_evaluation_plan_route_and_backend_remain_functional(db, client):
    """The HTML route and underlying API surface are not deleted, only the
    top-level nav entry pointing directly at them. A role holding only
    Evaluation Plan permissions (never talent_programs.view) is a real,
    still-supported persona and must not be denied access."""
    from routers import talent_ui as talent_ui_module

    assert 'evaluation-plans' in talent_ui_module.VIEWS
    permissions(db, 'talent_evaluation_plans.view')
    response = client.get('/talent/evaluation-plans')
    assert response.status_code == 200


def test_students_is_first_child_of_talent_nav_and_gated_by_students_view(db, client):
    permissions(db, 'talent_programs.view')
    response = client.get('/talent')
    assert response.status_code == 200
    # Without students.view, no Students link into the Talent tree appears.
    assert 'href="/students/"' not in response.text

    permissions(db, 'students.view')
    response = client.get('/talent')
    assert response.status_code == 200
    body = response.text
    students_index = body.index('href="/students/"')
    overview_index = body.index('href="/talent/overview"')
    programs_index = body.index('href="/talent/programs"')
    assert students_index < overview_index < programs_index
