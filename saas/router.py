from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from urllib.parse import quote_plus

import auth
from dependencies import get_db
import email_service
from saas import models, oauth, service

templates = Jinja2Templates(directory="templates")
router = APIRouter(prefix="/saas", tags=["saas"])


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


def _render(request: Request, template_name: str, context: dict, status_code: int = 200):
    merged = {"request": request, **context}
    return templates.TemplateResponse(request, template_name, merged, status_code=status_code)


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
    service.log_auth_event(
        db,
        event_type="login",
        account_id=account.id,
        request=request,
    )
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
    return _render(
        request,
        "saas/verification_sent.html",
        {"email": email, "warning": warning},
    )


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
        {
            "account": account,
            "identities": identities,
            "notice": request.query_params.get("notice", ""),
        },
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
