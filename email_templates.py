from dataclasses import dataclass
from html import escape


@dataclass(frozen=True)
class TransactionalEmail:
    subject: str
    text: str
    html: str


def render_transactional_email(
    *,
    subject: str,
    title: str,
    message: str,
    logo_url: str,
    action_label: str = "",
    action_url: str = "",
    fallback_label: str = "",
    expiry_note: str = "",
    security_note: str = "",
    details: tuple[str, ...] = (),
) -> TransactionalEmail:
    safe_title = escape(str(title or ""))
    safe_message = escape(str(message or ""))
    safe_logo_url = escape(str(logo_url or ""), quote=True)
    safe_action_label = escape(str(action_label or ""))
    safe_action_url = escape(str(action_url or ""), quote=True)
    safe_expiry_note = escape(str(expiry_note or ""))
    safe_security_note = escape(str(security_note or ""))
    safe_details = tuple(escape(str(detail or "")) for detail in details if str(detail or "").strip())

    detail_rows = "".join(
        (
            '<tr><td style="padding:0 0 10px;color:#334155;font-size:14px;line-height:1.55;">'
            f"{detail}</td></tr>"
        )
        for detail in safe_details
    )
    action_row = ""
    fallback_row = ""
    if safe_action_label and safe_action_url:
        action_row = f"""
        <tr>
          <td align="center" style="padding:20px 0 18px;">
            <a href="{safe_action_url}" style="display:inline-block;padding:13px 28px;border-radius:8px;background:#0a4ea3;color:#ffffff;font-size:15px;font-weight:700;text-decoration:none;">{safe_action_label}</a>
          </td>
        </tr>"""
        if fallback_label:
            fallback_row = f"""
        <tr>
          <td style="padding:0 0 18px;color:#64748b;font-size:12px;line-height:1.5;">
            {escape(fallback_label)}<br>
            <a href="{safe_action_url}" style="color:#0a4ea3;word-break:break-all;">{safe_action_url}</a>
          </td>
        </tr>"""

    note_rows = ""
    if safe_expiry_note:
        note_rows += f'<p style="margin:0 0 8px;color:#475569;font-size:12px;line-height:1.5;"><strong>Expiry:</strong> {safe_expiry_note}</p>'
    if safe_security_note:
        note_rows += f'<p style="margin:0;color:#475569;font-size:12px;line-height:1.5;"><strong>Security:</strong> {safe_security_note}</p>'

    html = f"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{safe_title}</title></head>
<body style="margin:0;padding:0;background:#eef3f8;font-family:Arial,Helvetica,sans-serif;color:#10233f;">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="background:#eef3f8;">
    <tr><td align="center" style="padding:36px 16px;">
      <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="max-width:600px;background:#ffffff;border:1px solid #dce6f1;border-radius:14px;box-shadow:0 12px 30px rgba(15,35,63,.08);overflow:hidden;">
        <tr><td align="center" style="padding:28px 32px 20px;border-bottom:1px solid #edf2f7;">
          <img src="{safe_logo_url}" width="190" alt="TIS Platform" style="display:block;width:190px;max-width:100%;height:auto;border:0;">
        </td></tr>
        <tr><td style="padding:30px 38px 28px;">
          <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0">
            <tr><td><h1 style="margin:0 0 14px;color:#102d55;font-size:25px;line-height:1.25;">{safe_title}</h1></td></tr>
            <tr><td style="padding:0 0 12px;color:#334155;font-size:15px;line-height:1.65;">{safe_message}</td></tr>
            {detail_rows}
            {action_row}
            {fallback_row}
            <tr><td style="padding:16px 18px;border-radius:9px;background:#f5f8fc;">{note_rows}</td></tr>
          </table>
        </td></tr>
        <tr><td align="center" style="padding:18px 24px;background:#0b2f5b;color:#ffffff;font-size:12px;font-weight:700;letter-spacing:.04em;">TIS Platform</td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""

    text_lines = ["TIS Platform", "", str(title or ""), "", str(message or "")]
    text_lines.extend(["", *[str(detail or "") for detail in details if str(detail or "").strip()]])
    if action_label and action_url:
        text_lines.extend(("", str(action_label), str(action_url)))
    if fallback_label and action_url:
        text_lines.extend(("", str(fallback_label), str(action_url)))
    if expiry_note:
        text_lines.extend(("", f"Expiry: {expiry_note}"))
    if security_note:
        text_lines.extend(("", f"Security: {security_note}"))
    text_lines.extend(("", "TIS Platform"))

    return TransactionalEmail(
        subject=str(subject or "").strip(),
        text="\n".join(text_lines).strip() + "\n",
        html=html,
    )


def build_email_verification_email(*, verification_url: str, logo_url: str) -> TransactionalEmail:
    return render_transactional_email(
        subject="Verify your email address | TIS Platform",
        title="Verify your email address",
        message="Confirm this email address to secure your TIS Account and continue school workspace setup.",
        logo_url=logo_url,
        action_label="Verify Email",
        action_url=verification_url,
        fallback_label="If the button does not work, open this verification link:",
        expiry_note="This verification link expires in one hour.",
        security_note="If you did not request this verification, you can safely ignore this email.",
    )


def build_password_reset_request_email(
    *,
    requester_display: str,
    user_id: str,
    platform_url: str,
    logo_url: str,
) -> TransactionalEmail:
    return render_transactional_email(
        subject="Password reset request | TIS Platform",
        title="Password reset request",
        message="A manual password reset request was submitted in TIS Platform.",
        logo_url=logo_url,
        action_label="Open TIS Platform",
        action_url=platform_url,
        fallback_label="If the button does not work, open TIS Platform here:",
        security_note="Review the account identity before changing any password.",
        details=(
            f"Requester: {requester_display}",
            f"User ID: {user_id}",
            "Follow the existing manual password reset process inside TIS.",
        ),
    )


def build_saas_password_reset_email(*, reset_url: str, logo_url: str) -> TransactionalEmail:
    return render_transactional_email(
        subject="Reset your TIS Account password | TIS Platform",
        title="Reset your TIS Account password",
        message="Use this secure link to choose a new password for your TIS Account.",
        logo_url=logo_url,
        action_label="Reset Password",
        action_url=reset_url,
        fallback_label="If the button does not work, open this password reset link:",
        expiry_note="This password reset link expires in one hour.",
        security_note="If you did not request a password reset, you can safely ignore this email.",
    )


def build_tenant_activation_email(
    *,
    organization_name: str,
    login_url: str,
    logo_url: str,
) -> TransactionalEmail:
    return render_transactional_email(
        subject=f"{organization_name} is now active | TIS Platform",
        title="Your School Workspace is active",
        message="Workspace Activation is complete and your TIS School Workspace is now ready.",
        logo_url=logo_url,
        action_label="Open TIS Login",
        action_url=login_url,
        fallback_label="If the button does not work, open the TIS login here:",
        security_note="Sign in with the same email and password you used for your TIS Account when password-based sign-in is available.",
        details=(
            f"Organization: {organization_name}",
            "Activation confirmed.",
            "Next steps: sign in, review your branches and academic year, then begin operational setup inside TIS.",
        ),
    )


def build_demo_request_received_email(*, organization_name: str, status_url: str, logo_url: str) -> TransactionalEmail:
    return render_transactional_email(
        subject="We received your TIS demo request",
        title="Your demo request is pending review",
        message="TIS received your demo request. The TIS team will review your request. We will email you after approval or decline.",
        logo_url=logo_url,
        action_label="View Demo Status",
        action_url=status_url,
        fallback_label="Open your demo status here:",
        details=(f"Organization: {organization_name}", "Continue using the same registered TIS Account."),
    )


def build_demo_approved_email(*, organization_name: str, start_date: str, expiry_date: str, login_url: str, registered_email: str, logo_url: str) -> TransactionalEmail:
    return render_transactional_email(
        subject="Your TIS demo is ready",
        title="Your seven-day TIS demo is active",
        message="Your demo request was approved and the same school workspace is ready to use.",
        logo_url=logo_url,
        action_label="Open TIS Login",
        action_url=login_url,
        fallback_label="Open the TIS login here:",
        details=(f"Organization: {organization_name}", f"Starts: {start_date}", f"Expires: {expiry_date}", f"Sign in using: {registered_email}"),
    )


def build_demo_declined_email(*, organization_name: str, status_url: str, logo_url: str) -> TransactionalEmail:
    return render_transactional_email(
        subject="Update on your TIS demo request",
        title="Your demo request was not approved",
        message="Thank you for your interest in TIS Platform. We are unable to approve this demo request at this time.",
        logo_url=logo_url,
        action_label="View Request Status",
        action_url=status_url,
        fallback_label="Open your request status here:",
        details=(f"Organization: {organization_name}", "Your submitted setup and request history remain available in your TIS Account."),
    )


def build_demo_day_six_reminder_email(*, organization_name: str, expiry_date: str, subscribe_url: str, logo_url: str) -> TransactionalEmail:
    return render_transactional_email(
        subject="Your TIS demo expires soon",
        title="Your demo expires soon",
        message="Your TIS demo is nearing its expiry. Your workspace data will remain preserved.",
        logo_url=logo_url,
        action_label="Subscribe Now",
        action_url=subscribe_url,
        fallback_label="Continue with TIS Platform here:",
        details=(f"Organization: {organization_name}", f"Expires: {expiry_date}"),
    )


def build_demo_expired_email(*, organization_name: str, subscribe_url: str, logo_url: str) -> TransactionalEmail:
    return render_transactional_email(
        subject="Your TIS demo has ended",
        title="Your demo has expired",
        message="The demo period has ended. Your workspace, users, branches, and data remain preserved.",
        logo_url=logo_url,
        action_label="Subscribe Now",
        action_url=subscribe_url,
        fallback_label="Continue with TIS Platform here:",
        details=(f"Organization: {organization_name}", "A verified subscription restores the same workspace."),
    )


def build_demo_subscription_invitation_email(*, organization_name: str, subscribe_url: str, logo_url: str) -> TransactionalEmail:
    return render_transactional_email(
        subject="Continue with TIS Platform",
        title="Continue with the same TIS workspace",
        message="Subscribe when you are ready to continue using the same preserved school workspace. No new workspace will be created.",
        logo_url=logo_url,
        action_label="Continue to Subscription",
        action_url=subscribe_url,
        fallback_label="Open the subscription path here:",
        details=(f"Organization: {organization_name}", "Payment has not yet occurred. Paid access begins only after secure payment confirmation."),
    )


def build_demo_reactivated_email(*, organization_name: str, expiry_date: str, login_url: str, logo_url: str) -> TransactionalEmail:
    return render_transactional_email(
        subject="Your TIS demo has been reactivated",
        title="Your demo access is active again",
        message="Your existing TIS workspace has been reactivated. Your users, branches, and data remain unchanged.",
        logo_url=logo_url,
        action_label="Open TIS Login",
        action_url=login_url,
        fallback_label="Open the TIS login here:",
        details=(f"Organization: {organization_name}", f"New expiry: {expiry_date}"),
    )


def build_demo_expiry_changed_email(*, organization_name: str, expiry_date: str, login_url: str, logo_url: str) -> TransactionalEmail:
    return render_transactional_email(
        subject="Your TIS demo expiry has been updated",
        title="Your demo schedule has been updated",
        message="Your TIS demo remains available in the same workspace through the updated expiry date.",
        logo_url=logo_url,
        action_label="Open TIS Login",
        action_url=login_url,
        fallback_label="Open the TIS login here:",
        details=(f"Organization: {organization_name}", f"New expiry: {expiry_date}"),
    )


def build_demo_manual_reminder_email(*, organization_name: str, expiry_date: str, subscribe_url: str, logo_url: str, variant: int) -> TransactionalEmail:
    messages = (
        "A friendly reminder that your TIS demo is in its final day. Your workspace data will remain preserved.",
        "Your TIS demo period is almost complete. You can subscribe to continue with the same workspace.",
        "There is still time to review TIS today. Your existing setup remains ready if you choose to continue.",
    )
    return render_transactional_email(
        subject="A reminder about your TIS demo",
        title="Your demo is in its final day",
        message=messages[int(variant) % len(messages)],
        logo_url=logo_url,
        action_label="Subscribe Now",
        action_url=subscribe_url,
        fallback_label="Continue with TIS Platform here:",
        details=(f"Organization: {organization_name}", f"Expires: {expiry_date}"),
    )


def build_demo_access_profile_changed_email(*, organization_name: str, profile_name: str, login_url: str, logo_url: str) -> TransactionalEmail:
    return render_transactional_email(
        subject="Your TIS demo access has been updated",
        title="Your demo feature access changed",
        message="The features available in your active TIS demo have been updated.",
        logo_url=logo_url,
        action_label="Open TIS Login",
        action_url=login_url,
        fallback_label="Open the TIS login here:",
        details=(f"Organization: {organization_name}", f"Access profile: {profile_name}"),
    )


def _draft_reminder_details(
    *,
    organization_name: str,
    progress_text: str,
    completion_percent: int,
    next_step: str,
    support_contact: str,
) -> tuple[str, ...]:
    details = []
    if str(organization_name or "").strip():
        details.append(f"Organization: {organization_name}")
    details.extend((
        f"Progress: {progress_text} ({int(completion_percent)}%)",
        f"Next step: {next_step}",
    ))
    if str(support_contact or "").strip():
        details.append(f"Support: {support_contact}")
    return tuple(details)


def build_first_draft_reminder_email(
    *,
    recipient_name: str,
    organization_name: str,
    progress_text: str,
    completion_percent: int,
    next_step: str,
    continue_url: str,
    logo_url: str,
    support_contact: str,
) -> TransactionalEmail:
    greeting = f"Hello {recipient_name}. " if str(recipient_name or "").strip() else ""
    return render_transactional_email(
        subject="Your TIS workspace is waiting for you",
        title="Your setup is safely saved",
        message=(
            f"{greeting}Everything you entered is safely saved. "
            "Continue your TIS School Workspace setup whenever you are ready."
        ),
        logo_url=logo_url,
        action_label="Continue Setup",
        action_url=continue_url,
        fallback_label="If the button does not work, sign in to your TIS Account here:",
        details=_draft_reminder_details(
            organization_name=organization_name,
            progress_text=progress_text,
            completion_percent=completion_percent,
            next_step=next_step,
            support_contact=support_contact,
        ),
    )


def build_second_draft_reminder_email(
    *,
    recipient_name: str,
    organization_name: str,
    progress_text: str,
    completion_percent: int,
    next_step: str,
    continue_url: str,
    logo_url: str,
    support_contact: str,
    include_ai: bool,
) -> TransactionalEmail:
    greeting = f"Hello {recipient_name}. " if str(recipient_name or "").strip() else ""
    benefits = [
        "teacher workforce planning",
        "academic operations",
        "branch management",
        "dashboards and reporting",
    ]
    if include_ai:
        benefits.append("AI-enabled capabilities included with your selected plan")
    details = list(_draft_reminder_details(
        organization_name=organization_name,
        progress_text=progress_text,
        completion_percent=completion_percent,
        next_step=next_step,
        support_contact=support_contact,
    ))
    details.append("TIS supports " + ", ".join(benefits) + ".")
    return render_transactional_email(
        subject="Your organization is one step closer to going live with TIS",
        title="Continue building your TIS workspace",
        message=(
            f"{greeting}Your saved setup brings your organization closer to a connected "
            "workspace for academic planning and day-to-day operations."
        ),
        logo_url=logo_url,
        action_label="Continue Setup",
        action_url=continue_url,
        fallback_label="If the button does not work, sign in to your TIS Account here:",
        details=tuple(details),
    )


def build_final_draft_reminder_email(
    *,
    recipient_name: str,
    organization_name: str,
    progress_text: str,
    completion_percent: int,
    next_step: str,
    continue_url: str,
    logo_url: str,
    support_contact: str,
    deletion_date: str,
    days_remaining: int,
    retention_days: int,
) -> TransactionalEmail:
    greeting = f"Hello {recipient_name}. " if str(recipient_name or "").strip() else ""
    day_label = "day" if int(days_remaining) == 1 else "days"
    details = list(_draft_reminder_details(
        organization_name=organization_name,
        progress_text=progress_text,
        completion_percent=completion_percent,
        next_step=next_step,
        support_contact=support_contact,
    ))
    details.append(f"Scheduled deletion date: {deletion_date}")
    return render_transactional_email(
        subject=f"Your TIS draft workspace will expire in {int(days_remaining)} {day_label}",
        title="Your draft workspace is nearing expiration",
        message=(
            f"{greeting}This unpaid draft has been inactive. It is scheduled for permanent deletion "
            f"after {int(retention_days)} days of inactivity. Sign in and continue setup to reset the inactivity period. "
            "If no activity occurs, the unpaid onboarding data will be removed."
        ),
        logo_url=logo_url,
        action_label="Continue Setup",
        action_url=continue_url,
        fallback_label="If the button does not work, sign in to your TIS Account here:",
        expiry_note=f"The current draft deletion date is {deletion_date}.",
        details=tuple(details),
    )
