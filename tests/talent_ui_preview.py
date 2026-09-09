"""Loopback-only synthetic M11 preview; never imported by the application.

Run: python tests/talent_ui_preview.py
Uses existing test providers and an in-memory test database only.
"""
import os
import sys
from pathlib import Path

os.environ['DATABASE_URL'] = 'sqlite://'
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.chdir(Path(__file__).resolve().parents[1])

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from auth import get_current_user
from dependencies import get_db, get_m10_organization_analytics_db
import models
from routers import (talent_ui, talent_programs, talent_evaluation_plans,
                     talent_assessments, talent_review_candidates, talent_learner_profiles,
                     talent_organization_analytics)
from talent_analytics_privacy import AllowAllTestPolicy, resolve_privacy_policy_provider
from talent_org_intelligence_service import (resolve_organization_analytics_availability_provider,
                                             resolve_organization_analytics_breadth_policy)
from test_talent_org_intelligence_queries import db, actor, permissions, AllowAvailability, AllowBreadth

fixture = db.__wrapped__()
session = next(fixture)
permissions(session, *set(v[1] for v in talent_ui.VIEWS.values()),
            'talent_analytics.view_students', 'talent_assessment_cycles.view',
            'talent_official_identifications.view')
for sid in (1001, 1002, 1003):
    session.add(models.Student(id=sid, school_group_id=1, first_name='Sample', last_name=f'Learner {sid-1000}'))
session.commit()

app = FastAPI(title='Synthetic M11 stakeholder preview')
app.mount('/static', StaticFiles(directory='static'), name='static')
for module in (talent_ui, talent_programs, talent_evaluation_plans, talent_assessments,
               talent_review_candidates, talent_learner_profiles, talent_organization_analytics):
    app.include_router(module.router)
app.dependency_overrides[get_db] = lambda: session
app.dependency_overrides[get_m10_organization_analytics_db] = lambda: session
app.dependency_overrides[get_current_user] = lambda: actor()
app.dependency_overrides[resolve_privacy_policy_provider] = lambda: AllowAllTestPolicy()
app.dependency_overrides[resolve_organization_analytics_availability_provider] = lambda: AllowAvailability()
app.dependency_overrides[resolve_organization_analytics_breadth_policy] = lambda: AllowBreadth()

@app.middleware('http')
async def preview_boundary(request, call_next):
    from fastapi.responses import PlainTextResponse
    if request.method not in {'GET', 'HEAD'}:
        return PlainTextResponse('This synthetic preview is read-only.', status_code=405)
    request.state.talent_synthetic_preview = True
    response = await call_next(request)
    response.headers['Cache-Control'] = 'no-store'
    return response

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='127.0.0.1', port=8765, workers=1)
