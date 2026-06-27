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


def build_tenant_activation_email(
    *,
    organization_name: str,
    login_url: str,
    logo_url: str,
) -> TransactionalEmail:
    return render_transactional_email(
        subject=f"{organization_name} is now active | TIS Platform",
        title="Your TIS organization is active",
        message="Provisioning is complete and your operational TIS workspace is now ready.",
        logo_url=logo_url,
        action_label="Open TIS Login",
        action_url=login_url,
        fallback_label="If the button does not work, open the operational login here:",
        security_note="Sign in with the same email and password you used for your SaaS account when password-based sign-in is available.",
        details=(
            f"Organization: {organization_name}",
            "Activation confirmed.",
            "Next steps: sign in, review your branches and academic year, then begin operational setup inside TIS.",
        ),
    )
