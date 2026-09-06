"""
Branded/localized auto-reply template renderer (open question #1).
Templates are stored in the `email_templates` table; an integration-specific
override (matched by integration_id + template_key + locale) takes priority
over the global default (integration_id IS NULL).
"""
from __future__ import annotations
from dataclasses import dataclass
from string import Template

from sqlalchemy.orm import Session
from app.models.document_intake import EmailTemplate

# ── Built-in fallback templates (seeded on first use if the table is empty) ──
_DEFAULT_TEMPLATES: dict[str, tuple[str, str]] = {
    "domain_rejected": (
        "Re: $subject — Domain Not Permitted",
        "<p>Hello,</p>"
        "<p>Thank you for your email. Unfortunately your domain is not authorised to send "
        "documents to this mailbox as per our policy, so your message could not be processed.</p>"
        "<p>If you believe this is an error, please contact the mailbox administrator.</p>"
        "<p><em>This is an automated response — please do not reply.</em></p>",
    ),
    "no_attachment": (
        "Re: $subject — No Attachment Found",
        "<p>Hello,</p>"
        "<p>Your email was received but did not contain any attachments to process. "
        "Please resend with the required document(s) attached.</p>"
        "<p><em>This is an automated response — please do not reply.</em></p>",
    ),
    "invalid_file_type": (
        "Re: $subject — Unsupported File Type",
        "<p>Hello,</p>"
        "<p>The following file(s) are not supported or exceed the size limit: <strong>$files</strong>.</p>"
        "<p>Please resend using an accepted format ($allowed_extensions).</p>"
        "<p><em>This is an automated response — please do not reply.</em></p>",
    ),
    "encrypted_file": (
        "Re: $subject — Password-Protected File(s)",
        "<p>Hello,</p>"
        "<p>The following file(s) are password-protected/encrypted and could not be processed: "
        "<strong>$files</strong>.</p>"
        "<p>Please resend without password protection — encrypted files are rejected and not processed.</p>"
        "<p><em>This is an automated response — please do not reply.</em></p>",
    ),
    "success": (
        "Re: $subject — Document Processed",
        "<p>Your document was received and processed successfully.</p>"
        "<p>Batch number: <strong>$batch_no</strong>.</p>"
        "<p><em>This is an automated response — please do not reply.</em></p>",
    ),
    "failure": (
        "Re: $subject — Document Processing Failed",
        "<p>We received your email, but the document could not be processed.</p>"
        "<p>Reason: $reason</p>"
        "<p><em>This is an automated response — please do not reply.</em></p>",
    ),
}


@dataclass
class RenderedTemplate:
    subject: str
    html_body: str


def seed_default_templates(db: Session) -> None:
    """Insert any missing built-in global templates without changing overrides."""
    existing_keys = {
        row.template_key
        for row in db.query(EmailTemplate.template_key)
        .filter(EmailTemplate.integration_id.is_(None))
        .all()
    }
    for key, (subject_tpl, html_tpl) in _DEFAULT_TEMPLATES.items():
        if key in existing_keys:
            continue
        db.add(
            EmailTemplate(
                integration_id=None,
                template_key=key,
                locale="en",
                subject_template=subject_tpl,
                html_body_template=html_tpl,
                is_active=True,
            )
        )
    db.commit()


def render_template(
    db: Session,
    template_key: str,
    context: dict,
    integration_id: int | None = None,
    locale: str = "en",
) -> RenderedTemplate:
    """
    Resolve and render a template: integration-specific override first,
    falling back to the global (integration_id=NULL) default, falling back
    further to the in-code default if no DB row exists at all.
    """
    row = None
    if integration_id is not None:
        row = (
            db.query(EmailTemplate)
            .filter(
                EmailTemplate.integration_id == integration_id,
                EmailTemplate.template_key == template_key,
                EmailTemplate.locale == locale,
                EmailTemplate.is_active == True,
            )
            .first()
        )

    if row is None:
        row = (
            db.query(EmailTemplate)
            .filter(
                EmailTemplate.integration_id.is_(None),
                EmailTemplate.template_key == template_key,
                EmailTemplate.locale == locale,
                EmailTemplate.is_active == True,
            )
            .first()
        )

    if row is not None:
        subject_tpl, html_tpl = row.subject_template, row.html_body_template
    else:
        subject_tpl, html_tpl = _DEFAULT_TEMPLATES.get(
            template_key, ("Re: $subject", "<p>$body</p>")
        )

    safe_context = {k: ("" if v is None else str(v)) for k, v in context.items()}
    subject = Template(subject_tpl).safe_substitute(safe_context)
    html_body = Template(html_tpl).safe_substitute(safe_context)
    if row is not None and row.logo_url:
        html_body = f'<p><img src="{row.logo_url}" alt="Company logo" style="max-height:56px;max-width:220px"></p>{html_body}'
    if row is not None and row.signature_html:
        html_body = f'{html_body}<div style="margin-top:24px">{row.signature_html}</div>'
    return RenderedTemplate(subject=subject, html_body=html_body)
