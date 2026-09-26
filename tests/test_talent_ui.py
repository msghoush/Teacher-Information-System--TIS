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
    assert '/static/js/talent-experience.js' in response.text
    assert '/static/js/talent-program-workspace.js' not in response.text
    assert '/static/js/talent-evaluation-workspace.js' not in response.text
    assert '/static/js/talent-operations.js' not in response.text
    # Deployment Acceptance Correction A: the tiny shared rubric visual module is
    # required by talent.js on EVERY view (Results & Analytics rubric sections and
    # Learner Profile badges); only the operational/workspace bundles are gated.
    assert '/static/js/talent-rubric-visual.js' in response.text
    assert '/static/css/talent-program-workspace.css' in response.text
    assert response.headers['cache-control'] == 'no-store'
    assert 'href="/talent/programs"' in response.text
    assert 'href="/talent/reviews"' not in response.text


@pytest.mark.parametrize(
    ('view', 'present', 'absent'),
    (
        # Configuration/System Configuration separation: the Program and Evaluation Plan
        # EDITOR bundles are never loaded by an operational Talent page. (The view
        # keys used here are view-only, so /talent/evaluation-plans renders its
        # read-only period list instead of redirecting a configuration actor.)
        ('programs', ('talent-rubric-visual.js', 'talent-program-grades.js'),
         ('talent-operations.js', 'talent-evaluation-workspace.js', 'talent-program-workspace.js')),
        ('evaluation-plans', ('talent-rubric-visual.js',),
         ('talent-operations.js', 'talent-program-workspace.js', 'talent-evaluation-workspace.js')),
        ('assessments', ('talent-rubric-visual.js', 'talent-operations.js'),
         ('talent-program-workspace.js', 'talent-evaluation-workspace.js')),
        ('reviews', ('talent-rubric-visual.js', 'talent-operations.js'),
         ('talent-program-workspace.js', 'talent-evaluation-workspace.js')),
        ('analytics', ('talent-rubric-visual.js',), ('talent-operations.js',
                                                      'talent-program-workspace.js', 'talent-evaluation-workspace.js')),
        ('overview', ('talent-rubric-visual.js',), ('talent-operations.js',
                                                     'talent-program-workspace.js', 'talent-evaluation-workspace.js')),
    ),
)
def test_talent_views_load_only_their_required_script_bundles(db, client, view, present, absent):
    permissions(db, *set(item[1] for item in talent_ui.VIEWS.values()))
    response = client.get(f'/talent/{view}')
    assert response.status_code == 200
    assert 'talent.js' in response.text and 'talent-experience.js' in response.text
    for asset in present:
        assert asset in response.text
    for asset in absent:
        assert asset not in response.text


# Every script global that static/js/talent.js (or its delegate modules) needs at
# script-evaluation or render time, per view. talent.js used to dereference
# window.TalentRubricVisual eagerly while the template only loaded that script on
# four views, so every other view threw at load time and stayed on the
# server-rendered "Loading your authorized workspace" placeholder forever.
REQUIRED_SCRIPTS_BY_VIEW = {
    'overview': ('talent-rubric-visual.js', 'talent-api-errors.js', 'talent-rubric-request.js', 'talent-student-identity.js'),
    'programs': ('talent-rubric-visual.js', 'talent-api-errors.js', 'talent-rubric-request.js', 'talent-student-identity.js', 'talent-program-grades.js'),
    'evaluation-plans': ('talent-rubric-visual.js', 'talent-api-errors.js', 'talent-rubric-request.js', 'talent-student-identity.js'),
    'assessments': ('talent-rubric-visual.js', 'talent-api-errors.js', 'talent-rubric-request.js', 'talent-student-identity.js', 'talent-operations.js'),
    'reviews': ('talent-rubric-visual.js', 'talent-api-errors.js', 'talent-rubric-request.js', 'talent-student-identity.js', 'talent-operations.js'),
    'learner-profile': ('talent-rubric-visual.js', 'talent-api-errors.js', 'talent-rubric-request.js', 'talent-student-identity.js'),
    'analytics': ('talent-rubric-visual.js', 'talent-api-errors.js', 'talent-rubric-request.js', 'talent-student-identity.js'),
    'talent-map': ('talent-rubric-visual.js', 'talent-api-errors.js', 'talent-rubric-request.js', 'talent-student-identity.js'),
    'portfolio': ('talent-rubric-visual.js', 'talent-api-errors.js', 'talent-rubric-request.js', 'talent-student-identity.js'),
    'branch': ('talent-rubric-visual.js', 'talent-api-errors.js', 'talent-rubric-request.js', 'talent-student-identity.js'),
    'overlap': ('talent-rubric-visual.js', 'talent-api-errors.js', 'talent-rubric-request.js', 'talent-student-identity.js'),
    'students': ('talent-rubric-visual.js', 'talent-api-errors.js', 'talent-rubric-request.js', 'talent-student-identity.js'),
    # Part 2: the Progress Over Time trend is drawn by the shared chart module.
    'longitudinal': ('talent-rubric-visual.js', 'talent-api-errors.js', 'talent-rubric-request.js', 'talent-student-identity.js', 'talent-charts.js'),
}


@pytest.mark.parametrize('view', list(talent_ui.VIEWS))
def test_every_view_loads_each_script_global_its_render_path_needs_before_talent_js(db, client, view):
    import re

    permissions(db, *set(item[1] for item in talent_ui.VIEWS.values()), 'talent_analytics.view_students')
    response = client.get(f'/talent/{view}')
    assert response.status_code == 200
    scripts = re.findall(r'<script src="[^"]*/static/js/([^"?]+)(?:\?[^"]*)?"', response.text)
    assert view in REQUIRED_SCRIPTS_BY_VIEW, f'declare the required script globals for the {view} view'
    # `defer` scripts execute in document order, so every dependency must precede talent.js.
    for asset in REQUIRED_SCRIPTS_BY_VIEW[view]:
        assert asset in scripts, f'{view} does not load {asset}'
        assert scripts.index(asset) < scripts.index('talent.js'), f'{asset} must execute before talent.js on {view}'


def test_server_rendered_loader_is_marked_for_deterministic_replacement(db, client):
    permissions(db, 'talent_programs.view')
    html = client.get('/talent/overview').text
    assert 'id="tp-content" aria-busy="true"' in html
    assert 'data-initial-loading>Loading your authorized workspace' in html
    assert '<noscript>' in html
    assert 'role="status" aria-live="polite" class="tp-sr-status"' in html


def test_talent_page_bounds_authorized_permission_projection_reuse(db, client, monkeypatch):
    import auth

    permissions(db, *set(item[1] for item in talent_ui.VIEWS.values()))
    original = auth.get_allowed_permission_keys
    calls = []

    def counted(*args, **kwargs):
        calls.append((args, kwargs))
        return original(*args, **kwargs)

    monkeypatch.setattr(auth, 'get_allowed_permission_keys', counted)
    response = client.get('/talent/overview')
    assert response.status_code == 200
    # Route gating, the shell's commercial feature checks, and the final
    # projection stay independently authorized, but the old per-key loop
    # (roughly 25 extra full projections) must never return.
    assert len(calls) <= 3


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


CONFIG_MUTATION_KEYS = (
    'talent_programs.manage', 'talent_programs.govern', 'talent_programs.delete_competency',
    'talent_programs.delete_rubric_level', 'talent_evaluation_plans.manage',
    'talent_evaluation_plans.govern', 'talent_assessment_cycles.manage', 'talent_assessment_cycles.govern',
)


def test_branch_scope_is_read_only_for_shared_configuration_with_explanatory_copy(db, client):
    # Final-closure Part B: even holding every configuration key (e.g. a Branch-scoped
    # Administrator), a Branch-scoped actor gets NO enabled mutation capability and
    # sees the shared-by-all-Branches read-only notice on both configuration views.
    permissions(db, 'talent_programs.view', 'talent_evaluation_plans.view', *CONFIG_MUTATION_KEYS)
    client.app.dependency_overrides[get_current_user] = lambda: actor(scope='BRANCH')
    for view in ('programs', 'evaluation-plans'):
        response = client.get(f'/talent/{view}')
        assert response.status_code == 200
        config = _tp_config(response.text)
        for key in CONFIG_MUTATION_KEYS:
            assert config['permissions'][key] is False, key
        assert config['permissions']['talent_programs.view'] is True
        assert 'data-shared-config="read-only"' in response.text
        assert 'Shared by all Branches.' in response.text
        assert 'managed by your organization Administrator' in response.text
        assert 'Changes you make here apply to every Branch.' not in response.text


def test_organization_administrator_sees_one_configure_link_and_no_configuration_editor_on_the_operational_page(db, client):
    # System Configuration separation: even an organization Administrator configures ONLY
    # in System Configuration. The operational Programs page carries one non-mutating link
    # and never loads the editor bundles; semantic hints stay for operational use
    # (e.g. selecting a planned Evaluation Period), the API gates stay authoritative.
    permissions(db, 'talent_programs.view', 'talent_evaluation_plans.view', *CONFIG_MUTATION_KEYS)
    response = client.get('/talent/programs')
    assert response.status_code == 200
    config = _tp_config(response.text)
    assert config['configurationUrl'] == '/system-configuration/talent-potential'
    assert 'data-shared-config="configure-link"' in response.text
    assert 'href="/system-configuration/talent-potential"' in response.text
    assert 'Configure in System Configuration' in response.text
    assert 'Changes you make here apply to every Branch.' not in response.text
    assert 'talent-program-workspace.js' not in response.text
    assert 'talent-evaluation-workspace.js' not in response.text
    # Non-configuration views never carry the notice.
    permissions(db, 'talent_analytics.view')
    assert 'data-shared-config' not in client.get('/talent/analytics').text


def test_no_configure_link_without_organization_configuration_authority(db, client):
    permissions(db, 'talent_programs.view', 'talent_evaluation_plans.view')  # view only
    response = client.get('/talent/programs')
    assert _tp_config(response.text)['configurationUrl'] == ''
    assert 'data-shared-config="read-only"' in response.text
    assert '/system-configuration/talent-potential' not in response.text
    permissions(db, *CONFIG_MUTATION_KEYS)
    client.app.dependency_overrides[get_current_user] = lambda: actor(scope='BRANCH')
    branch_response = client.get('/talent/programs')
    assert _tp_config(branch_response.text)['configurationUrl'] == ''
    assert '/system-configuration/talent-potential' not in branch_response.text


def test_old_evaluation_plan_deep_link_redirects_only_an_authorized_actor_to_system_configuration(db, client):
    permissions(db, 'talent_evaluation_plans.view', 'talent_evaluation_plans.manage')
    response = client.get('/talent/evaluation-plans?program_id=7&academic_year_id=100&x=<b>', follow_redirects=False)
    assert response.status_code == 302
    assert response.headers['location'] == '/system-configuration/talent-potential?tab=evaluation-periods&program_id=7&academic_year_id=100'
    # A Branch-scoped actor holding the same keys gets the read-only period list, not a redirect.
    client.app.dependency_overrides[get_current_user] = lambda: actor(scope='BRANCH')
    assert client.get('/talent/evaluation-plans', follow_redirects=False).status_code == 200


def test_evaluation_plan_action_permissions_reach_browser_payload(db, client):
    # Operational hint: selecting a planned Evaluation Period (Student Assessments) is not
    # configuration and keeps its semantic permission hints on the operational page.
    permissions(db, 'talent_assessments.view', 'talent_evaluation_plans.view',
                'talent_evaluation_plans.manage',
                'talent_evaluation_plans.govern',
                'talent_evaluation_plans.select_period')
    response = client.get('/talent/assessments')
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

    db.merge(models.Student(id=1001, school_group_id=1, first_name='Alya', last_name='Learner', status='active'))
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
    # Acceptance B (deliberate update of a pinned expectation): Talent Review is
    # legacy history and is no longer a primary navigation peer.
    assert 'href="/talent/reviews"' not in nav
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


def test_talent_review_is_legacy_history_not_a_primary_navigation_peer(db, client):
    """Acceptance B: Review Candidate / Official Identification are legacy history. The sidebar and the
    Talent Overview never present "Talent Review" as a current workflow peer; the legacy route stays
    reachable (same permission gate, same permission enforcement) under an explicit Legacy title."""
    permissions(db, *set(item[1] for item in talent_ui.VIEWS.values()))
    for view in ('overview', 'programs', 'assessments', 'analytics'):
        html = client.get(f'/talent/{view}').text
        assert 'Talent Review' not in html, view
        assert 'href="/talent/reviews"' not in html, view
    assert talent_ui.VIEWS['reviews'][0] == 'Legacy Review & Identification History'
    assert talent_ui.VIEWS['reviews'][1] == 'talent_review_candidates.view'
    legacy = client.get('/talent/reviews')
    assert legacy.status_code == 200
    assert 'Legacy Review &amp; Identification History' in legacy.text


def test_legacy_history_route_still_requires_its_permission(db, client):
    permissions(db, 'talent_programs.view')
    assert client.get('/talent/reviews').status_code == 403


def test_primary_talent_navigation_lists_only_current_workflow_views():
    import ui_shell
    import inspect
    source = inspect.getsource(ui_shell)
    assert '"label": "Talent Review"' not in source
    assert '"href": "/talent/reviews"' not in source
    for label in ('Student Assessments', 'Results & Analytics', 'Programs', 'Overview'):
        assert f'"label": "{label}"' in source


# --- Deployment Acceptance Batch 1: global Branch context + never-hangs loading ----------


def _tp_config(html):
    import json
    import re

    return json.loads(re.search(r'<script type="application/json" id="tp-config">(.*?)</script>', html, re.S).group(1))


def test_workspace_publishes_the_server_validated_active_branch(db, client):
    permissions(db, 'talent_programs.view')
    # Part 1 amendment: for an organization actor the validated sidebar Branch
    # (scope_branch_id) is published as the DEFAULT page Branch and is not a lock;
    # a legacy scope_all_branches attribute grants and changes nothing.
    scoped = actor()
    scoped.scope_branch_id = 10
    client.app.dependency_overrides[get_current_user] = lambda: scoped
    config = _tp_config(client.get('/talent/overview').text)
    assert config['branch'] == 10 and config['branchName'] == 'North' and config['branchLocked'] is False
    legacy = actor()
    legacy.scope_branch_id = 10
    legacy.scope_all_branches = True
    client.app.dependency_overrides[get_current_user] = lambda: legacy
    legacy_config = _tp_config(client.get('/talent/overview').text)
    assert legacy_config['branch'] == 10 and legacy_config['branchLocked'] is False


def test_workspace_never_publishes_a_branch_outside_the_actors_tenant(db):
    app = FastAPI()
    app.mount('/static', StaticFiles(directory='static'), name='static')
    app.include_router(talent_ui.router)
    foreign = actor()
    foreign.scope_branch_id = 20  # a Branch of ANOTHER SchoolGroup ("Foreign")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: foreign
    permissions(db, 'talent_programs.view')
    config = _tp_config(TestClient(app).get('/talent/overview').text)
    assert config['branch'] is None and config['branchName'] is None


def test_talent_assets_are_versioned_by_content_and_the_loader_has_a_watchdog(db, client):
    import re

    permissions(db, 'talent_programs.view')
    html = client.get('/talent/overview').text
    versioned = re.findall(r'/static/((?:js|css)/talent[^"?]*)\?v=([0-9a-f]{12})"', html)
    assert len(versioned) >= 8
    for asset, version in versioned:
        assert version == talent_ui.talent_asset_version(asset), asset
        assert client.get(f'/static/{asset}?v={version}').status_code == 200
    # A static file that changes gets a new URL (no stale mixed-version cache).
    assert 'data-server-loader' in html and 'LIMIT_MS = 15000' in html
