"""System Configuration > Talent & Potential Configuration (batch: System Configuration +
Operational User Flow Separation, Part 1: information architecture, routing, gating, shell).

Organization-level Talent configuration is defined only in System Configuration. Access is
the existing semantic Talent configuration permission AND organization/global access scope
(the same authority the canonical /api/talent/* configuration routes enforce with
403 organization_authority_required). UI visibility never replaces those API gates; this
file only proves that the new page is visible/reachable to exactly those actors.
"""
import re

import pytest
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.testclient import TestClient

import authorization
import talent_configuration_access
from auth import get_current_user
from dependencies import get_db
from routers import talent_configuration_ui, talent_ui
from test_talent_org_intelligence_queries import actor, db, permissions  # noqa: F401  (fixtures)
from ui_shell import _build_nav_items

PATH = '/system-configuration/talent-potential'


@pytest.fixture
def client(db):
    app = FastAPI()
    app.mount('/static', StaticFiles(directory='static'), name='static')
    app.include_router(talent_ui.router)
    app.include_router(talent_configuration_ui.router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: actor()
    return TestClient(app)


def test_authorized_organization_actor_loads_the_workspace_shell(db, client):
    permissions(db, 'talent_programs.view', 'talent_programs.manage', 'talent_evaluation_plans.manage')
    response = client.get(PATH)
    assert response.status_code == 200
    assert response.headers['cache-control'] == 'no-store'
    html = response.text
    assert 'Talent &amp; Potential Configuration' in html
    assert 'Configure organization-wide Talent Programs, eligible Grades, Rubrics, Competencies, KPIs and Evaluation Periods.' in html
    assert 'Shared across all Branches' in html
    assert 'Organization-wide configuration' in html and 'Changes here apply across all Branches.' in html
    assert 'href="/system-configuration"' in html  # breadcrumb: System Configuration > Talent & Potential
    # The three-column shell: Programs list | selected Program center | detail drawer.
    for marker in ('id="tpc-program-list"', 'id="tpc-content"', 'id="tpc-drawer"', 'data-tpc-action="new-program"'):
        assert marker in html, marker
    # The existing canonical editors and the shell are mounted here...
    for script in ('talent-program-workspace.js', 'talent-evaluation-workspace.js', 'talent-configuration.js'):
        assert script in html
    # ...with server-derived capability hints for the existing can() mechanism.
    config = _config(html)
    assert config['permissions']['talent_programs.manage'] is True
    assert config['permissions']['talent_evaluation_plans.manage'] is True


def test_tabs_are_limited_to_real_concepts(db, client):
    permissions(db, 'talent_programs.view', 'talent_programs.manage')
    html = client.get(PATH).text
    tabs = re.findall(r'data-tpc-tab="([a-z-]+)"', html)
    assert tabs == ['programs', 'evaluation-periods']
    # No invented global resources: Rubrics are competency-owned per Program/Grade and
    # KPI/criteria are per-Program-Framework, so neither exists as a top-level tab.
    for fake in ('Rubric Templates', 'KPI &amp; Criteria', '>Settings<', 'Achievement Indicators'):
        assert fake not in html, fake


def test_evaluation_plan_only_actor_with_organization_scope_is_authorized(db, client):
    permissions(db, 'talent_evaluation_plans.view', 'talent_evaluation_plans.manage')
    assert client.get(PATH).status_code == 200


@pytest.mark.parametrize('keys', [
    (),  # a normal user with no Talent permission at all
    ('talent_programs.view', 'talent_evaluation_plans.view', 'talent_assessments.view'),  # operational Talent user
    ('talent_programs.view', 'talent_analytics.view'),
])
def test_normal_users_are_denied_server_side(db, client, keys):
    permissions(db, *keys) if keys else None
    response = client.get(PATH, follow_redirects=False)
    assert response.status_code == 403
    assert 'id="tpc-config"' not in response.text


def test_branch_scoped_actor_holding_every_configuration_key_is_denied(db, client):
    permissions(db, 'talent_programs.view', 'talent_programs.manage', 'talent_programs.govern',
                'talent_evaluation_plans.manage', 'talent_evaluation_plans.govern',
                'talent_assessment_cycles.manage')
    client.app.dependency_overrides[get_current_user] = lambda: actor(scope='BRANCH')
    response = client.get(PATH, follow_redirects=False)
    assert response.status_code == 403
    assert 'shared by all Branches' in response.text
    assert 'id="tpc-config"' not in response.text


def test_authorization_rule_is_a_single_shared_definition(db):
    permissions(db, 'talent_programs.manage')
    assert talent_configuration_access.is_authorized(actor(), {'talent_programs.manage'}) is True
    assert talent_configuration_access.is_authorized(actor(scope='BRANCH'), {'talent_programs.manage'}) is False
    assert talent_configuration_access.is_authorized(actor(), {'talent_programs.view'}) is False
    assert talent_configuration_access.is_authorized(None, {'talent_programs.manage'}) is False
    # No new permission key: the rule only names existing semantic keys.
    import permission_registry
    for key in talent_configuration_access.TALENT_CONFIGURATION_KEYS:
        assert key in permission_registry.ALL_PERMISSION_KEYS


def test_deep_link_builder_is_allow_listed_and_digit_only():
    build = talent_configuration_access.configuration_url
    assert build() == PATH
    assert build(tab='evaluation-periods', program_id='7', academic_year_id='100') == f'{PATH}?tab=evaluation-periods&program_id=7&academic_year_id=100'
    assert build(tab='<script>', program_id='7;drop', academic_year_id='x') == PATH


def test_system_configuration_sidebar_child_only_for_authorized_actors():
    items = lambda flag: _build_nav_items(  # noqa: E731
        '/system-configuration/talent-potential', can=lambda key: True, can_any=lambda *keys: True,
        can_configure_talent=flag,
    )
    config = next(item for item in items(True) if item['href'] == '/system-configuration')
    assert [child['label'] for child in config['children']] == [
        'Organization', 'Academic Setup', 'Users & Access', 'Talent & Potential',
    ]
    assert config['children'][-1]['href'] == PATH
    assert config['children'][-1]['active'] is True
    assert [child['label'] for child in next(item for item in items(False) if item['href'] == '/system-configuration')['children']] == [
        'Organization', 'Academic Setup', 'Users & Access',
    ]


def test_operational_talent_navigation_uses_requested_tree_order():
    allowed = {'students.view', 'talent_programs.view', 'talent_assessments.view', 'talent_analytics.view'}
    items = _build_nav_items('/talent', can=lambda key: key in allowed, can_any=lambda *keys: any(k in allowed for k in keys))
    talent = next(item for item in items if item['href'] == '/talent')
    assert [child['label'] for child in talent['children']] == ['Overview', 'Students', 'Programs', 'Student Assessments', 'Results & Analytics']
    assert all('system-configuration' not in child['href'] for child in talent['children'])


def test_real_application_registers_route_module_and_middleware_rule(db):
    import main
    from tests import permission_audit_support as support
    routes = {(method, path) for method, path, _endpoint in support.all_routes()}
    assert ('GET', PATH) in routes
    rule = authorization._find_permission_rule(PATH, 'GET')
    assert rule is not None
    assert set(rule.permission_keys) == set(talent_configuration_access.TALENT_CONFIGURATION_KEYS)
    module = next(item for item in main.CONFIGURATION_MODULES if item['key'] == 'talent-potential')
    assert module['label'] == 'Talent & Potential'
    assert module['description'] == 'Programs, Rubrics, Competencies, KPIs & Evaluation Periods'
    assert module['note'] == 'Organization-wide - Shared across all Branches'


def test_configuration_module_is_listed_only_for_authorized_organization_actors(db):
    import main
    permissions(db, 'talent_programs.manage', 'configuration.view')
    listed = lambda user: {m['key'] for m in main._get_configuration_modules('overview', db, user)}  # noqa: E731
    assert 'talent-potential' in listed(actor())
    assert 'talent-potential' not in listed(actor(scope='BRANCH'))
    permissions(db, 'talent_programs.manage', allow=False)
    assert 'talent-potential' not in listed(actor())


def _config(html):
    import json
    match = re.search(r'<script type="application/json" id="tpc-config">(.*?)</script>', html, re.S)
    assert match
    return json.loads(match.group(1))
