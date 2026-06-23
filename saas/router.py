from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from urllib.parse import quote_plus

import auth
from dependencies import get_db
import email_service
from saas import billing_service, models, oauth, pricing_service, service

templates = Jinja2Templates(directory="templates")
router = APIRouter(prefix="/saas", tags=["saas"])
admin_router = APIRouter(prefix="/saas-admin", tags=["saas-admin"])


def _safe_next(next_path: str | None) -> str:
    cleaned = str(next_path or "").strip()
    return cleaned if cleaned.startswith("/saas") else "/saas/account"


def _current_account(request: Request, db: Session):
    return service.get_current_account(db, request)


def _require_account(request: Request, db: Session):
    account = _current_account(request, db)
    if not account:
        raise HTTPException(status_code=401, detail="SaaS authentication is required.")
    session_row = service.get_session_from_request(db, request)
    return account, session_row


def _require_platform_owner(request: Request, db: Session):
    current_user = auth.get_current_user(request, db)
    if not current_user or not auth.is_platform_owner(current_user):
        raise HTTPException(status_code=403, detail="Platform Owner access is required.")
    return current_user


def _render(request: Request, template_name: str, context: dict, status_code: int = 200):
    merged = {"request": request, **context}
    return templates.TemplateResponse(request, template_name, merged, status_code=status_code)


def _redirect_error(path: str, message: str):
    separator = "&" if "?" in path else "?"
    return RedirectResponse(f"{path}{separator}error={quote_plus(str(message or ''))}", status_code=302)


def _onboarding_context(db: Session, account, organization):
    summary = service.build_pending_dashboard_summary(db, account)
    progress = summary["progress"] if summary else service.get_or_create_pending_progress(db, organization)
    academic_setup = service.get_or_create_academic_setup(db, organization)
    primary_contact = service.get_primary_contact(db, organization)
    branches = service.list_pending_branches(db, organization)
    return {
        "account": account,
        "organization": organization,
        "progress": progress,
        "academic_setup": academic_setup,
        "primary_contact": primary_contact,
        "branches": branches,
        "journey_card": summary,
    }


def _plan_context(db: Session, account, organization):
    summary = service.build_pending_dashboard_summary(db, account)
    checkout_summary = billing_service.build_checkout_summary(db, organization)
    return {
        "account": account,
        "organization": organization,
        "journey_card": summary,
        "plan_catalog": pricing_service.build_plan_catalog(
            db,
            country_code=str(getattr(organization, "country_code", "") or ""),
        ),
        "current_plan_selection": checkout_summary["selection"] if checkout_summary else None,
        "checkout_summary": checkout_summary,
    }


@router.get("", response_class=HTMLResponse)
def saas_root(request: Request, db: Session = Depends(get_db)):
    account = _current_account(request, db)
    return RedirectResponse("/saas/account" if account else "/saas/login", status_code=302)


@router.get("/login", response_class=HTMLResponse, name="saas_login_page")
def login_page(
    request: Request,
    error: str = Query(""),
    email: str = Query(""),
    db: Session = Depends(get_db),
):
    if _current_account(request, db):
        return RedirectResponse("/saas/account", status_code=302)
    return _render(
        request,
        "saas/login.html",
        {
            "error": error,
            "email": email,
            "google_enabled": oauth.is_provider_configured("google"),
            "microsoft_enabled": oauth.is_provider_configured("microsoft"),
        },
    )


@router.get("/signup", response_class=HTMLResponse, name="saas_signup_page")
def signup_page(
    request: Request,
    error: str = Query(""),
    warning: str = Query(""),
    email: str = Query(""),
    first_name: str = Query(""),
    last_name: str = Query(""),
    db: Session = Depends(get_db),
):
    if _current_account(request, db):
        return RedirectResponse("/saas/account", status_code=302)
    return _render(
        request,
        "saas/signup.html",
        {
            "error": error,
            "warning": warning,
            "email": email,
            "first_name": first_name,
            "last_name": last_name,
            "google_enabled": oauth.is_provider_configured("google"),
            "microsoft_enabled": oauth.is_provider_configured("microsoft"),
        },
    )


@router.post("/auth/signup")
def signup(
    request: Request,
    first_name: str = Form(""),
    last_name: str = Form(""),
    email: str = Form(...),
    password: str = Form(...),
    confirm_password: str = Form(...),
    db: Session = Depends(get_db),
):
    if service.is_rate_limited(
        db,
        event_type="signup",
        request=request,
        max_attempts=service.SIGNUP_RATE_LIMIT_ATTEMPTS,
        window_minutes=service.SIGNUP_RATE_LIMIT_WINDOW_MINUTES,
    ):
        return RedirectResponse(
            url="/saas/signup?error=Too+many+signup+attempts.+Please+try+again+later.",
            status_code=302,
        )
    if str(password or "") != str(confirm_password or ""):
        return RedirectResponse(
            url=(
                "/saas/signup?error=Password+confirmation+does+not+match."
                f"&email={quote_plus(str(email or ''))}"
                f"&first_name={quote_plus(str(first_name or ''))}"
                f"&last_name={quote_plus(str(last_name or ''))}"
            ),
            status_code=302,
        )
    try:
        account, policy = service.create_account(
            db,
            email=email,
            password=password,
            first_name=first_name,
            last_name=last_name,
            request=request,
        )
        service.send_verification_email(db, account, request)
        db.commit()
    except email_service.EmailDeliveryError:
        db.rollback()
        return RedirectResponse(
            url="/saas/signup?error=Verification+email+could+not+be+sent.+Please+try+again.",
            status_code=302,
        )
    except ValueError as exc:
        db.rollback()
        return RedirectResponse(
            url=(
                "/saas/signup?error="
                + quote_plus(str(exc))
                + f"&email={quote_plus(str(email or ''))}"
                + f"&first_name={quote_plus(str(first_name or ''))}"
                + f"&last_name={quote_plus(str(last_name or ''))}"
            ),
            status_code=302,
        )
    return RedirectResponse(
        url="/saas/auth/verification-sent?email="
        f"{quote_plus(str(account.email or ''))}&warning={quote_plus(str(policy.warning or ''))}",
        status_code=302,
    )


@router.post("/auth/login")
def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    next_path: str = Form("/saas/account"),
    db: Session = Depends(get_db),
):
    if service.is_rate_limited(
        db,
        event_type="login",
        request=request,
        event_status="failed",
        max_attempts=service.LOGIN_RATE_LIMIT_ATTEMPTS,
        window_minutes=service.LOGIN_RATE_LIMIT_WINDOW_MINUTES,
    ):
        return RedirectResponse(
            url="/saas/login?error=Too+many+login+attempts.+Please+wait+before+trying+again.",
            status_code=302,
        )
    account = service.authenticate_account(db, email, password)
    if not account:
        service.log_auth_event(
            db,
            event_type="login",
            event_status="failed",
            request=request,
            details={"email": auth.normalize_email(email)},
        )
        db.commit()
        return RedirectResponse(
            url="/saas/login?error=Invalid+email+or+password.&email=" + quote_plus(str(email or "")),
            status_code=302,
        )
    session_token, csrf_token, _session_row = service.create_session(db, account, request=request)
    service.log_auth_event(db, event_type="login", account_id=account.id, request=request)
    db.commit()
    response = RedirectResponse(url=_safe_next(next_path), status_code=302)
    return service.set_session_cookies(
        response,
        session_token=session_token,
        csrf_token=csrf_token,
        request=request,
    )


@router.post("/auth/logout")
def logout(request: Request, db: Session = Depends(get_db)):
    session_row = service.get_session_from_request(db, request)
    if session_row:
        service.revoke_session(db, session_row, reason="logout")
        service.log_auth_event(
            db,
            event_type="logout",
            account_id=session_row.saas_account_id,
            request=request,
        )
        db.commit()
    response = RedirectResponse("/saas/login", status_code=302)
    return service.clear_session_cookies(response, request)


@router.get("/auth/verification-sent", response_class=HTMLResponse)
def verification_sent_page(
    request: Request,
    email: str = Query(""),
    warning: str = Query(""),
):
    return _render(request, "saas/verification_sent.html", {"email": email, "warning": warning})


@router.get("/auth/verify-email", response_class=HTMLResponse)
def verify_email_page(
    request: Request,
    token: str = Query(""),
    db: Session = Depends(get_db),
):
    account, error = service.verify_email_token(db, token)
    if not account:
        db.rollback()
        return _render(request, "saas/verify_email.html", {"error": error, "success": ""}, status_code=400)
    db.commit()
    return _render(
        request,
        "saas/verify_email.html",
        {"success": "Your SaaS account email has been verified. You can now sign in.", "error": ""},
    )


@router.post("/auth/resend-verification")
def resend_verification(
    request: Request,
    email: str = Form(...),
    db: Session = Depends(get_db),
):
    if service.is_rate_limited(
        db,
        event_type="verification_sent",
        request=request,
        max_attempts=service.VERIFICATION_RATE_LIMIT_ATTEMPTS,
        window_minutes=service.VERIFICATION_RATE_LIMIT_WINDOW_MINUTES,
    ):
        return RedirectResponse(
            url="/saas/login?error=Too+many+verification+requests.+Please+try+again+later.&email="
            + quote_plus(str(email or "")),
            status_code=302,
        )
    account = service.get_account_by_email(db, email)
    if account:
        try:
            service.send_verification_email(db, account, request)
            db.commit()
        except email_service.EmailDeliveryError:
            db.rollback()
            return RedirectResponse(
                url="/saas/login?error=Verification+email+could+not+be+sent.&email=" + quote_plus(str(email or "")),
                status_code=302,
            )
    return RedirectResponse(
        url="/saas/auth/verification-sent?email=" + quote_plus(str(email or "")),
        status_code=302,
    )


@router.get("/account", response_class=HTMLResponse)
def account_dashboard(request: Request, db: Session = Depends(get_db)):
    account, session_row = _require_account(request, db)
    sessions = db.query(models.SaaSSession).filter(
        models.SaaSSession.saas_account_id == account.id,
        models.SaaSSession.revoked_at.is_(None),
    ).order_by(models.SaaSSession.last_seen_at.desc()).all()
    onboarding_summary = service.build_pending_dashboard_summary(db, account)
    db.commit()
    return _render(
        request,
        "saas/account.html",
        {
            "account": account,
            "session_row": session_row,
            "sessions": sessions,
            "csrf_token": request.cookies.get(service.SAAS_CSRF_COOKIE, ""),
            "notice": request.query_params.get("notice", ""),
            "onboarding_summary": onboarding_summary,
        },
    )


@router.get("/plans", response_class=HTMLResponse)
def public_plan_catalog(
    request: Request,
    country_code: str = Query(""),
    db: Session = Depends(get_db),
):
    return _render(
        request,
        "saas/plan_catalog.html",
        {
            "account": _current_account(request, db),
            "plan_catalog": pricing_service.build_plan_catalog(db, country_code=country_code),
        },
    )


@router.get("/account/profile", response_class=HTMLResponse)
def account_profile(request: Request, db: Session = Depends(get_db)):
    account, _session_row = _require_account(request, db)
    db.commit()
    return _render(
        request,
        "saas/profile.html",
        {
            "account": account,
            "csrf_token": request.cookies.get(service.SAAS_CSRF_COOKIE, ""),
            "notice": request.query_params.get("notice", ""),
        },
    )


@router.post("/account/profile")
def update_profile(
    request: Request,
    first_name: str = Form(""),
    last_name: str = Form(""),
    csrf_token: str = Form(""),
    db: Session = Depends(get_db),
):
    account, session_row = _require_account(request, db)
    if service.hash_value(csrf_token) != str(session_row.csrf_token_hash or ""):
        raise HTTPException(status_code=403, detail="Invalid CSRF token.")
    account.first_name = str(first_name or "").strip()[:120]
    account.last_name = str(last_name or "").strip()[:120]
    db.commit()
    return RedirectResponse("/saas/account/profile?notice=Profile+updated.", status_code=302)


@router.get("/account/security", response_class=HTMLResponse)
def account_security(request: Request, db: Session = Depends(get_db)):
    account, _session_row = _require_account(request, db)
    identities = db.query(models.SaaSAuthIdentity).filter(
        models.SaaSAuthIdentity.saas_account_id == account.id
    ).order_by(models.SaaSAuthIdentity.provider.asc()).all()
    db.commit()
    return _render(
        request,
        "saas/security.html",
        {"account": account, "identities": identities, "notice": request.query_params.get("notice", "")},
    )


@router.get("/account/sessions", response_class=HTMLResponse)
def account_sessions(request: Request, db: Session = Depends(get_db)):
    account, session_row = _require_account(request, db)
    sessions = db.query(models.SaaSSession).filter(
        models.SaaSSession.saas_account_id == account.id
    ).order_by(models.SaaSSession.last_seen_at.desc()).all()
    db.commit()
    return _render(
        request,
        "saas/sessions.html",
        {
            "account": account,
            "sessions": sessions,
            "current_session_id": session_row.id,
            "csrf_token": request.cookies.get(service.SAAS_CSRF_COOKIE, ""),
            "notice": request.query_params.get("notice", ""),
        },
    )


@router.post("/account/sessions/revoke-others")
def revoke_other_sessions(
    request: Request,
    csrf_token: str = Form(""),
    db: Session = Depends(get_db),
):
    account, session_row = _require_account(request, db)
    if service.hash_value(csrf_token) != str(session_row.csrf_token_hash or ""):
        raise HTTPException(status_code=403, detail="Invalid CSRF token.")
    service.revoke_other_sessions(db, account, session_row.id)
    db.commit()
    return RedirectResponse("/saas/account/sessions?notice=Other+sessions+revoked.", status_code=302)


@router.post("/account/sessions/{session_id}/revoke")
def revoke_single_session(
    session_id: int,
    request: Request,
    csrf_token: str = Form(""),
    db: Session = Depends(get_db),
):
    account, current_session = _require_account(request, db)
    if service.hash_value(csrf_token) != str(current_session.csrf_token_hash or ""):
        raise HTTPException(status_code=403, detail="Invalid CSRF token.")
    target = db.query(models.SaaSSession).filter(
        models.SaaSSession.id == session_id,
        models.SaaSSession.saas_account_id == account.id,
    ).first()
    if target and target.id != current_session.id:
        service.revoke_session(db, target, reason="manual_revoke")
    db.commit()
    return RedirectResponse("/saas/account/sessions?notice=Session+revoked.", status_code=302)


@router.get("/onboarding")
def onboarding_root(request: Request, db: Session = Depends(get_db)):
    account, _session_row = _require_account(request, db)
    organization = service.get_pending_organization_for_account(db, account)
    db.commit()
    if not organization:
        return RedirectResponse("/saas/account", status_code=302)
    return RedirectResponse(service.organization_step_url(organization), status_code=302)


@router.post("/onboarding/start")
def start_onboarding(request: Request, db: Session = Depends(get_db)):
    account, _session_row = _require_account(request, db)
    organization = service.create_pending_organization(db, account, request=request)
    progress = service.recalculate_pending_progress(db, organization)
    service.update_pending_dashboard_status(account, organization, progress)
    db.commit()
    return RedirectResponse(service.organization_step_url(organization), status_code=302)


@router.get("/onboarding/{organization_uuid}/resume")
def resume_onboarding(organization_uuid: str, request: Request, db: Session = Depends(get_db)):
    account, _session_row = _require_account(request, db)
    organization = service.get_owned_pending_organization(db, account, organization_uuid)
    if not organization:
        db.rollback()
        return RedirectResponse("/saas/account?notice=No+pending+organization+draft+was+found.", status_code=302)
    db.commit()
    return RedirectResponse(service.organization_step_url(organization), status_code=302)


@router.get("/onboarding/{organization_uuid}/organization", response_class=HTMLResponse)
def organization_step(
    organization_uuid: str,
    request: Request,
    error: str = Query(""),
    db: Session = Depends(get_db),
):
    account, _session_row = _require_account(request, db)
    organization = service.get_owned_pending_organization(db, account, organization_uuid)
    if not organization:
        db.rollback()
        return RedirectResponse("/saas/account", status_code=302)
    context = _onboarding_context(db, account, organization)
    db.commit()
    context.update({"account": account, "error": error, "step_key": "organization"})
    return _render(request, "saas/onboarding_organization.html", context)


@router.post("/onboarding/{organization_uuid}/organization")
async def save_organization_step(
    organization_uuid: str,
    request: Request,
    organization_name: str = Form(""),
    legal_name: str = Form(""),
    website: str = Form(""),
    primary_domain: str = Form(""),
    phone: str = Form(""),
    educational_program: str = Form(""),
    country_code: str = Form(""),
    country_name: str = Form(""),
    region_name: str = Form(""),
    city_name: str = Form(""),
    district_name: str = Form(""),
    neighborhood_name: str = Form(""),
    school_type: str = Form(""),
    expected_branch_count: str = Form(""),
    expected_student_count: str = Form(""),
    expected_teacher_count: str = Form(""),
    estimated_staff_users: str = Form(""),
    timezone: str = Form(""),
    save_action: str = Form("continue"),
    organization_logo: UploadFile | None = File(None),
    db: Session = Depends(get_db),
):
    account, _session_row = _require_account(request, db)
    organization = service.get_owned_pending_organization(db, account, organization_uuid)
    if not organization:
        db.rollback()
        return RedirectResponse("/saas/account", status_code=302)
    try:
        service.save_organization_profile(
            db,
            organization,
            organization_name=organization_name,
            legal_name=legal_name,
            website=website,
            primary_domain=primary_domain,
            phone=phone,
            educational_program=educational_program,
            country_code=country_code,
            country_name=country_name,
            region_name=region_name,
            city_name=city_name,
            district_name=district_name,
            neighborhood_name=neighborhood_name,
            school_type=school_type,
            expected_branch_count=expected_branch_count,
            expected_student_count=expected_student_count,
            expected_teacher_count=expected_teacher_count,
            estimated_staff_users=estimated_staff_users,
            timezone=timezone,
            logo_file=organization_logo,
        )
        progress = service.save_draft(db, account, organization, current_step="branches")
        service.log_pending_event(db, organization=organization, account=account, event_type="organization_saved", details={"completion_percent": progress.completion_percent})
        db.commit()
    except ValueError as exc:
        db.rollback()
        return _redirect_error(f"/saas/onboarding/{organization_uuid}/organization", str(exc))
    if str(save_action or "").strip().lower() == "save_exit":
        return RedirectResponse("/saas/account?notice=Draft+saved.", status_code=302)
    return RedirectResponse(f"/saas/onboarding/{organization_uuid}/branches", status_code=302)


@router.get("/onboarding/{organization_uuid}/branches", response_class=HTMLResponse)
def branches_step(
    organization_uuid: str,
    request: Request,
    error: str = Query(""),
    db: Session = Depends(get_db),
):
    account, _session_row = _require_account(request, db)
    organization = service.get_owned_pending_organization(db, account, organization_uuid)
    if not organization:
        db.rollback()
        return RedirectResponse("/saas/account", status_code=302)
    context = _onboarding_context(db, account, organization)
    db.commit()
    context.update({"account": account, "error": error, "step_key": "branches"})
    return _render(request, "saas/onboarding_branches.html", context)


@router.post("/onboarding/{organization_uuid}/branches")
def save_branches_step(
    organization_uuid: str,
    request: Request,
    branch_name: list[str] = Form([]),
    location: list[str] = Form([]),
    country_code: list[str] = Form([]),
    country_name: list[str] = Form([]),
    region_name: list[str] = Form([]),
    city_name: list[str] = Form([]),
    district_name: list[str] = Form([]),
    neighborhood_name: list[str] = Form([]),
    save_action: str = Form("continue"),
    db: Session = Depends(get_db),
):
    account, _session_row = _require_account(request, db)
    organization = service.get_owned_pending_organization(db, account, organization_uuid)
    if not organization:
        db.rollback()
        return RedirectResponse("/saas/account", status_code=302)
    branch_rows = []
    max_rows = max(
        len(branch_name),
        len(location),
        len(country_code),
        len(country_name),
        len(region_name),
        len(city_name),
        len(district_name),
        len(neighborhood_name),
        0,
    )
    for index in range(max_rows):
        branch_rows.append(
            {
                "branch_name": branch_name[index] if index < len(branch_name) else "",
                "location": location[index] if index < len(location) else "",
                "country_code": country_code[index] if index < len(country_code) else "",
                "country_name": country_name[index] if index < len(country_name) else "",
                "region_name": region_name[index] if index < len(region_name) else "",
                "city_name": city_name[index] if index < len(city_name) else "",
                "district_name": district_name[index] if index < len(district_name) else "",
                "neighborhood_name": neighborhood_name[index] if index < len(neighborhood_name) else "",
            }
        )
    try:
        service.replace_branches(db, organization, branch_rows)
        progress = service.save_draft(db, account, organization, current_step="academic_setup")
        service.log_pending_event(db, organization=organization, account=account, event_type="branches_saved", details={"completion_percent": progress.completion_percent})
        db.commit()
    except ValueError as exc:
        db.rollback()
        return _redirect_error(f"/saas/onboarding/{organization_uuid}/branches", str(exc))
    if str(save_action or "").strip().lower() == "save_exit":
        return RedirectResponse("/saas/account?notice=Draft+saved.", status_code=302)
    return RedirectResponse(f"/saas/onboarding/{organization_uuid}/academic_setup", status_code=302)


@router.get("/onboarding/{organization_uuid}/academic_setup", response_class=HTMLResponse)
def academic_setup_step(
    organization_uuid: str,
    request: Request,
    error: str = Query(""),
    db: Session = Depends(get_db),
):
    account, _session_row = _require_account(request, db)
    organization = service.get_owned_pending_organization(db, account, organization_uuid)
    if not organization:
        db.rollback()
        return RedirectResponse("/saas/account", status_code=302)
    context = _onboarding_context(db, account, organization)
    db.commit()
    context.update({"account": account, "error": error, "step_key": "academic_setup"})
    return _render(request, "saas/onboarding_academic_setup.html", context)


@router.post("/onboarding/{organization_uuid}/academic_setup")
def save_academic_setup_step(
    organization_uuid: str,
    request: Request,
    first_academic_year_name: str = Form(""),
    create_default_branch: str = Form(""),
    notes: str = Form(""),
    save_action: str = Form("continue"),
    db: Session = Depends(get_db),
):
    account, _session_row = _require_account(request, db)
    organization = service.get_owned_pending_organization(db, account, organization_uuid)
    if not organization:
        db.rollback()
        return RedirectResponse("/saas/account", status_code=302)
    try:
        service.save_academic_setup(
            db,
            organization,
            first_academic_year_name=first_academic_year_name,
            create_default_branch=create_default_branch,
            notes=notes,
        )
        progress = service.save_draft(db, account, organization, current_step="contacts")
        service.log_pending_event(db, organization=organization, account=account, event_type="academic_setup_saved", details={"completion_percent": progress.completion_percent})
        db.commit()
    except ValueError as exc:
        db.rollback()
        return _redirect_error(f"/saas/onboarding/{organization_uuid}/academic_setup", str(exc))
    if str(save_action or "").strip().lower() == "save_exit":
        return RedirectResponse("/saas/account?notice=Draft+saved.", status_code=302)
    return RedirectResponse(f"/saas/onboarding/{organization_uuid}/contacts", status_code=302)


@router.get("/onboarding/{organization_uuid}/contacts", response_class=HTMLResponse)
def contacts_step(
    organization_uuid: str,
    request: Request,
    error: str = Query(""),
    db: Session = Depends(get_db),
):
    account, _session_row = _require_account(request, db)
    organization = service.get_owned_pending_organization(db, account, organization_uuid)
    if not organization:
        db.rollback()
        return RedirectResponse("/saas/account", status_code=302)
    context = _onboarding_context(db, account, organization)
    db.commit()
    context.update({"account": account, "error": error, "step_key": "contacts"})
    return _render(request, "saas/onboarding_contacts.html", context)


@router.post("/onboarding/{organization_uuid}/contacts")
def save_contacts_step(
    organization_uuid: str,
    request: Request,
    first_name: str = Form(""),
    last_name: str = Form(""),
    job_title: str = Form(""),
    email: str = Form(""),
    phone: str = Form(""),
    save_action: str = Form("continue"),
    db: Session = Depends(get_db),
):
    account, _session_row = _require_account(request, db)
    organization = service.get_owned_pending_organization(db, account, organization_uuid)
    if not organization:
        db.rollback()
        return RedirectResponse("/saas/account", status_code=302)
    try:
        service.save_primary_contact(
            db,
            organization,
            first_name=first_name or account.first_name or "",
            last_name=last_name or account.last_name or "",
            job_title=job_title,
            email=email or account.email or "",
            phone=phone,
        )
        progress = service.save_draft(db, account, organization, current_step="review")
        service.log_pending_event(db, organization=organization, account=account, event_type="contacts_saved", details={"completion_percent": progress.completion_percent})
        db.commit()
    except ValueError as exc:
        db.rollback()
        return _redirect_error(f"/saas/onboarding/{organization_uuid}/contacts", str(exc))
    if str(save_action or "").strip().lower() == "save_exit":
        return RedirectResponse("/saas/account?notice=Draft+saved.", status_code=302)
    return RedirectResponse(f"/saas/onboarding/{organization_uuid}/review", status_code=302)


@router.get("/onboarding/{organization_uuid}/review", response_class=HTMLResponse)
def review_step(
    organization_uuid: str,
    request: Request,
    error: str = Query(""),
    db: Session = Depends(get_db),
):
    account, _session_row = _require_account(request, db)
    organization = service.get_owned_pending_organization(db, account, organization_uuid)
    if not organization:
        db.rollback()
        return RedirectResponse("/saas/account", status_code=302)
    context = _onboarding_context(db, account, organization)
    db.commit()
    context.update({"account": account, "error": error, "step_key": "review"})
    return _render(request, "saas/onboarding_review.html", context)


@router.post("/onboarding/{organization_uuid}/save-draft")
def save_draft_exit(
    organization_uuid: str,
    request: Request,
    current_step: str = Form("organization"),
    db: Session = Depends(get_db),
):
    account, _session_row = _require_account(request, db)
    organization = service.get_owned_pending_organization(db, account, organization_uuid)
    if not organization:
        db.rollback()
        return RedirectResponse("/saas/account", status_code=302)
    service.save_draft(db, account, organization, current_step=current_step)
    db.commit()
    return RedirectResponse("/saas/account?notice=Draft+saved.", status_code=302)


@router.post("/onboarding/{organization_uuid}/submit")
def submit_onboarding(
    organization_uuid: str,
    request: Request,
    db: Session = Depends(get_db),
):
    account, _session_row = _require_account(request, db)
    organization = service.get_owned_pending_organization(db, account, organization_uuid)
    if not organization:
        db.rollback()
        return RedirectResponse("/saas/account", status_code=302)
    try:
        service.submit_pending_organization(db, account, organization)
        db.commit()
    except ValueError as exc:
        db.rollback()
        return _redirect_error(f"/saas/onboarding/{organization_uuid}/review", str(exc))
    return RedirectResponse("/saas/account?notice=Organization+is+ready+for+checkout.", status_code=302)


@router.get("/onboarding/{organization_uuid}/plan", response_class=HTMLResponse)
def plan_selection_step(
    organization_uuid: str,
    request: Request,
    error: str = Query(""),
    db: Session = Depends(get_db),
):
    account, _session_row = _require_account(request, db)
    organization = service.get_owned_pending_organization(db, account, organization_uuid)
    if not organization:
        db.rollback()
        return RedirectResponse("/saas/account", status_code=302)
    try:
        billing_service.ensure_ready_for_checkout(organization)
    except ValueError as exc:
        db.rollback()
        return RedirectResponse(f"/saas/account?notice={quote_plus(str(exc))}", status_code=302)
    context = _plan_context(db, account, organization)
    db.commit()
    context.update({"error": error})
    return _render(request, "saas/plan_selection.html", context)


@router.post("/onboarding/{organization_uuid}/plan")
def select_plan_step(
    organization_uuid: str,
    request: Request,
    plan_id: str = Form(""),
    billing_interval: str = Form("monthly"),
    db: Session = Depends(get_db),
):
    account, _session_row = _require_account(request, db)
    organization = service.get_owned_pending_organization(db, account, organization_uuid)
    if not organization:
        db.rollback()
        return RedirectResponse("/saas/account", status_code=302)
    try:
        selection = billing_service.select_plan(
            db,
            organization,
            plan_id=int(plan_id or 0),
            billing_interval=billing_interval,
        )
        service.update_pending_dashboard_status(account, organization, service.recalculate_pending_progress(db, organization))
        db.commit()
    except (ValueError, TypeError) as exc:
        db.rollback()
        return _redirect_error(f"/saas/onboarding/{organization_uuid}/plan", str(exc))
    return RedirectResponse(
        f"/saas/onboarding/{organization_uuid}/checkout?notice={quote_plus('Plan selected successfully.')}",
        status_code=302,
    )


@router.get("/onboarding/{organization_uuid}/checkout", response_class=HTMLResponse)
def checkout_summary_step(
    organization_uuid: str,
    request: Request,
    error: str = Query(""),
    notice: str = Query(""),
    db: Session = Depends(get_db),
):
    account, _session_row = _require_account(request, db)
    organization = service.get_owned_pending_organization(db, account, organization_uuid)
    if not organization:
        db.rollback()
        return RedirectResponse("/saas/account", status_code=302)
    context = _plan_context(db, account, organization)
    db.commit()
    context.update({"error": error, "notice": notice})
    return _render(request, "saas/checkout_summary.html", context)


@router.post("/onboarding/{organization_uuid}/checkout/start")
def prepare_checkout_step(
    organization_uuid: str,
    request: Request,
    db: Session = Depends(get_db),
):
    account, _session_row = _require_account(request, db)
    organization = service.get_owned_pending_organization(db, account, organization_uuid)
    if not organization:
        db.rollback()
        return RedirectResponse("/saas/account", status_code=302)
    try:
        billing_service.create_or_update_checkout_session(db, organization)
        service.update_pending_dashboard_status(account, organization, service.recalculate_pending_progress(db, organization))
        db.commit()
    except ValueError as exc:
        db.rollback()
        return _redirect_error(f"/saas/onboarding/{organization_uuid}/checkout", str(exc))
    return RedirectResponse(
        f"/saas/onboarding/{organization_uuid}/checkout?notice={quote_plus('Checkout summary is ready.')}",
        status_code=302,
    )


@router.get("/onboarding/{organization_uuid}/billing-status", response_class=HTMLResponse)
def billing_status_step(
    organization_uuid: str,
    request: Request,
    db: Session = Depends(get_db),
):
    account, _session_row = _require_account(request, db)
    organization = service.get_owned_pending_organization(db, account, organization_uuid)
    if not organization:
        db.rollback()
        return RedirectResponse("/saas/account", status_code=302)
    context = _plan_context(db, account, organization)
    db.commit()
    return _render(request, "saas/billing_status.html", context)


@admin_router.get("/pending-organizations", response_class=HTMLResponse)
def pending_organizations_dashboard(
    request: Request,
    status: str = Query(""),
    db: Session = Depends(get_db),
):
    current_user = _require_platform_owner(request, db)
    organizations = service.list_pending_organizations(db, status=status)
    cards = [service.build_pending_card(db, organization) for organization in organizations]
    db.commit()
    return _render(
        request,
        "saas/admin_pending_organizations.html",
        {
            "current_user": current_user,
            "cards": cards,
            "status_filter": status,
            "notice": request.query_params.get("notice", ""),
        },
    )


@admin_router.get("/pending-organizations/{organization_uuid}", response_class=HTMLResponse)
def pending_organization_detail(
    organization_uuid: str,
    request: Request,
    db: Session = Depends(get_db),
):
    current_user = _require_platform_owner(request, db)
    organization = service.get_pending_organization_by_uuid(db, organization_uuid)
    if not organization:
        db.rollback()
        raise HTTPException(status_code=404, detail="Pending organization not found.")
    card = service.build_pending_card(db, organization)
    academic_setup = service.get_or_create_academic_setup(db, organization)
    primary_contact = service.get_primary_contact(db, organization)
    branches = service.list_pending_branches(db, organization)
    events = service.list_pending_events(db, organization)
    notes = service.list_pending_notes(db, organization)
    db.commit()
    return _render(
        request,
        "saas/admin_pending_organization_detail.html",
        {
            "current_user": current_user,
            "card": card,
            "organization": organization,
            "academic_setup": academic_setup,
            "primary_contact": primary_contact,
            "branches": branches,
            "events": events,
            "notes": notes,
            "notice": request.query_params.get("notice", ""),
            "error": request.query_params.get("error", ""),
        },
    )


@admin_router.post("/pending-organizations/{organization_uuid}/notes")
def add_pending_organization_note(
    organization_uuid: str,
    request: Request,
    note: str = Form(""),
    db: Session = Depends(get_db),
):
    current_user = _require_platform_owner(request, db)
    organization = service.get_pending_organization_by_uuid(db, organization_uuid)
    if not organization:
        db.rollback()
        raise HTTPException(status_code=404, detail="Pending organization not found.")
    try:
        service.add_pending_note(
            db,
            organization,
            author_type="platform_owner",
            author_ref=str(getattr(current_user, "user_id", "") or ""),
            note=note,
            is_internal=True,
        )
        service.log_pending_event(
            db,
            organization=organization,
            event_type="note_added",
            details={"author_user_id": str(getattr(current_user, "user_id", "") or "")},
        )
        db.commit()
    except ValueError as exc:
        db.rollback()
        return RedirectResponse(
            f"/saas-admin/pending-organizations/{organization_uuid}?error={quote_plus(str(exc))}",
            status_code=302,
        )
    return RedirectResponse(
        f"/saas-admin/pending-organizations/{organization_uuid}?notice=Note+saved.",
        status_code=302,
    )


@admin_router.post("/pending-organizations/{organization_uuid}/status")
def update_pending_organization_status(
    organization_uuid: str,
    request: Request,
    status: str = Form(""),
    rejection_reason: str = Form(""),
    db: Session = Depends(get_db),
):
    current_user = _require_platform_owner(request, db)
    organization = service.get_pending_organization_by_uuid(db, organization_uuid)
    if not organization:
        db.rollback()
        raise HTTPException(status_code=404, detail="Pending organization not found.")
    try:
        service.update_pending_status(
            db,
            organization,
            status=status,
            reviewer_user_id=str(getattr(current_user, "user_id", "") or ""),
            rejection_reason=rejection_reason,
        )
        service.log_pending_event(
            db,
            organization=organization,
            event_type="status_changed",
            details={"status": str(status or "").strip().lower()},
        )
        db.commit()
    except ValueError as exc:
        db.rollback()
        return RedirectResponse(
            f"/saas-admin/pending-organizations/{organization_uuid}?error={quote_plus(str(exc))}",
            status_code=302,
        )
    return RedirectResponse(
        f"/saas-admin/pending-organizations/{organization_uuid}?notice=Status+updated.",
        status_code=302,
    )


@router.get("/auth/{provider}/start")
def oauth_start(provider: str, request: Request):
    authorization_url, state_token, verifier = oauth.build_authorization_url(request, provider)
    response = RedirectResponse(authorization_url, status_code=302)
    response.set_cookie(
        oauth.OAUTH_STATE_COOKIE,
        state_token,
        **auth.secure_cookie_kwargs(request, max_age=oauth.OAUTH_MAX_AGE_SECONDS),
    )
    response.set_cookie(
        oauth.OAUTH_PKCE_COOKIE,
        verifier,
        **auth.secure_cookie_kwargs(request, max_age=oauth.OAUTH_MAX_AGE_SECONDS),
    )
    return response


@router.get("/auth/{provider}/callback")
def oauth_callback(
    provider: str,
    request: Request,
    code: str = Query(""),
    state: str = Query(""),
    db: Session = Depends(get_db),
):
    cookie_state = str(request.cookies.get(oauth.OAUTH_STATE_COOKIE) or "").strip()
    code_verifier = str(request.cookies.get(oauth.OAUTH_PKCE_COOKIE) or "").strip()
    if not state or not cookie_state or state != cookie_state:
        return PlainTextResponse("OAuth state validation failed.", status_code=400)
    state_payload = oauth.decode_state_token(state)
    if not state_payload or state_payload.get("provider") != str(provider or "").strip().lower():
        return PlainTextResponse("OAuth state is invalid or expired.", status_code=400)
    try:
        token_payload = oauth.exchange_code_for_tokens(request, provider, code, code_verifier)
        claims = oauth.verify_identity_token(provider, token_payload, state_payload.get("nonce", ""))
        account, policy = service.link_or_create_social_account(
            db,
            provider=provider,
            provider_subject=str(claims.get("sub") or "").strip(),
            email=claims.get("email"),
            email_verified=bool(claims.get("email_verified", False)),
            first_name=claims.get("given_name") or "",
            last_name=claims.get("family_name") or "",
            tenant_hint=claims.get("tid") or "",
            profile=claims,
            request=request,
        )
        session_token, csrf_token, _session_row = service.create_session(db, account, request=request)
        db.commit()
    except ValueError as exc:
        db.rollback()
        return RedirectResponse("/saas/login?error=" + quote_plus(str(exc)), status_code=302)
    except Exception:
        db.rollback()
        return PlainTextResponse("OAuth sign-in could not be completed.", status_code=400)
    notice = quote_plus(str(policy.warning or ""))
    response = RedirectResponse(
        f"/saas/account?notice={notice}" if notice else "/saas/account",
        status_code=302,
    )
    response.delete_cookie(oauth.OAUTH_STATE_COOKIE, **auth.secure_cookie_kwargs(request))
    response.delete_cookie(oauth.OAUTH_PKCE_COOKIE, **auth.secure_cookie_kwargs(request))
    return service.set_session_cookies(
        response,
        session_token=session_token,
        csrf_token=csrf_token,
        request=request,
    )
