"""
Auto-reply templates — one per rule of the intake flow.

Templates live in ``email_templates``; a mailbox-specific row (integration_id)
overrides the global default (integration_id IS NULL), which in turn falls back
to the built-in text below. Placeholders use ``$name``. Values are HTML-escaped,
except keys ending in ``_html`` which the pipeline builds from escaped parts.
"""
from __future__ import annotations
import html
import re
from dataclasses import dataclass
from string import Template

from sqlalchemy.orm import Session
from app.models.document_intake import EmailTemplate

_FOOTER = "<p><em>This is an automated response — please do not reply to this message.</em></p>"

# Order = order of the rules; also the order shown in the UI.
DEFAULT_TEMPLATES: dict[str, tuple[str, str]] = {
    "domain_rejected": (
        "Re: $subject — Email domain not valid",
        "<p>Hello,</p>"
        "<p>Thank you for your email. Your email domain (<strong>$domain</strong>) is not valid "
        "for this mailbox, so your email has not been processed.</p>"
        "<p>If you believe this is an error, please contact us from a registered email address.</p>"
        + _FOOTER,
    ),
    "acknowledgement": (
        "Re: $subject — We have received your email",
        "<p>Greetings,</p>"
        "<p>Thank you for your email. We have received it and will review it and send you the "
        "status shortly.</p>"
        "<p>Reference number: <strong>$batch_no</strong></p>"
        + _FOOTER,
    ),
    "no_attachment": (
        "Re: $subject — No attachment found",
        "<p>Hello,</p>"
        "<p>Your email does not have any attachment to proceed further. Please upload the "
        "documents (accepted formats: $allowed_extensions) and send them again so we can process them.</p>"
        "<p>Reference number: <strong>$batch_no</strong></p>"
        + _FOOTER,
    ),
    "invalid_file_type": (
        "Re: $subject — Unsupported attachment(s)",
        "<p>Hello,</p>"
        "<p>Your email could not be processed because the following attachment(s) are not supported:</p>"
        "$file_list_html"
        "<p>Accepted formats: <strong>$allowed_extensions</strong> (up to $max_file_size_mb MB per file). "
        "Please send all documents again in an accepted format.</p>"
        "<p>Reference number: <strong>$batch_no</strong></p>"
        + _FOOTER,
    ),
    "invalid_attachments": (
        "Re: $subject — Attachment(s) could not be opened",
        "<p>Hello,</p>"
        "<p>The following attachment(s) are not valid — they are password-protected, encrypted "
        "or cannot be read:</p>"
        "$file_list_html"
        "<p>Please review them and send the documents again (without a password) so we can process them.</p>"
        "<p>Reference number: <strong>$batch_no</strong></p>"
        + _FOOTER,
    ),
    "success": (
        "Re: $subject — Processed successfully",
        "<p>Hello,</p>"
        "<p>Your email has been processed successfully. Below are the attachments as you shared:</p>"
        "$file_list_html"
        "<p>Reference number: <strong>$batch_no</strong></p>"
        + _FOOTER,
    ),
}

TEMPLATE_LABELS = {
    "domain_rejected": "1. Domain not valid",
    "acknowledgement": "2. Email received (acknowledgement)",
    "no_attachment": "3. No attachment",
    "invalid_file_type": "3. Unsupported attachment type",
    "invalid_attachments": "4. Protected / unreadable attachments",
    "success": "5. Processed successfully",
}

PLACEHOLDERS = {
    "domain_rejected": ["subject", "domain"],
    "acknowledgement": ["subject", "batch_no"],
    "no_attachment": ["subject", "batch_no", "allowed_extensions"],
    "invalid_file_type": ["subject", "batch_no", "file_list_html", "allowed_extensions", "max_file_size_mb"],
    "invalid_attachments": ["subject", "batch_no", "file_list_html"],
    "success": ["subject", "batch_no", "file_list_html"],
}

# Built-in texts shipped by earlier versions. Rows still holding them are upgraded
# to the new defaults; rows an admin edited are left alone.
_LEGACY_DEFAULTS: dict[str, list[tuple[str, str]]] = {
    "domain_rejected": [(
        "Re: $subject — Domain Not Permitted",
        "<p>Hello,</p>"
        "<p>Thank you for your email. Unfortunately your domain is not authorised to send "
        "documents to this mailbox as per our policy, so your message could not be processed.</p>"
        "<p>If you believe this is an error, please contact the mailbox administrator.</p>"
        "<p><em>This is an automated response — please do not reply.</em></p>",
    )],
    "no_attachment": [(
        "Re: $subject — No Attachment Found",
        "<p>Hello,</p>"
        "<p>Your email was received but did not contain any attachments to process. "
        "Please resend with the required document(s) attached.</p>"
        "<p><em>This is an automated response — please do not reply.</em></p>",
    )],
    "invalid_file_type": [(
        "Re: $subject — Unsupported File Type",
        "<p>Hello,</p>"
        "<p>The following file(s) are not supported or exceed the size limit: <strong>$files</strong>.</p>"
        "<p>Please resend using an accepted format ($allowed_extensions).</p>"
        "<p><em>This is an automated response — please do not reply.</em></p>",
    )],
    "success": [(
        "Re: $subject — Document Processed",
        "<p>Your document was received and processed successfully.</p>"
        "<p>Batch number: <strong>$batch_no</strong>.</p>"
        "<p><em>This is an automated response — please do not reply.</em></p>",
    )],
}


@dataclass
class RenderedTemplate:
    subject: str
    html_body: str


def file_list_html(items: list[tuple[str, str | None]]) -> str:
    """``[(filename, reason_or_None), ...]`` -> an HTML list built from escaped text."""
    rows = []
    for name, reason in items:
        entry = f"<strong>{html.escape(name)}</strong>"
        if reason:
            entry += f" — {html.escape(reason)}"
        rows.append(f"<li>{entry}</li>")
    return f"<ul>{''.join(rows)}</ul>" if rows else ""


def seed_default_templates(db: Session) -> None:
    """Insert missing global templates and upgrade untouched old built-in texts."""
    existing = {
        row.template_key: row
        for row in db.query(EmailTemplate).filter(EmailTemplate.integration_id.is_(None)).all()
    }
    for key, (subject_tpl, html_tpl) in DEFAULT_TEMPLATES.items():
        row = existing.get(key)
        if row is None:
            db.add(EmailTemplate(
                integration_id=None, template_key=key, locale="en",
                subject_template=subject_tpl, html_body_template=html_tpl, is_active=True,
            ))
        elif (row.subject_template, row.html_body_template) in _LEGACY_DEFAULTS.get(key, []):
            row.subject_template, row.html_body_template = subject_tpl, html_tpl
    db.commit()


def _find_row(db: Session, template_key: str, integration_id: int | None, locale: str):
    query = db.query(EmailTemplate).filter(
        EmailTemplate.template_key == template_key,
        EmailTemplate.locale == locale,
        EmailTemplate.is_active == True,
    )
    if integration_id is not None:
        row = query.filter(EmailTemplate.integration_id == integration_id).first()
        if row is not None:
            return row
    return query.filter(EmailTemplate.integration_id.is_(None)).first()


def render_template(
    db: Session,
    template_key: str,
    context: dict,
    integration_id: int | None = None,
    locale: str = "en",
) -> RenderedTemplate:
    """Render a template: mailbox override -> global row -> built-in default."""
    row = _find_row(db, template_key, integration_id, locale)
    if row is not None:
        subject_tpl, html_tpl = row.subject_template, row.html_body_template
    else:
        subject_tpl, html_tpl = DEFAULT_TEMPLATES.get(template_key, ("Re: $subject", "<p>$body</p>"))

    # Context values (subject, filenames, reasons) come from external senders:
    # plain text in the subject line, HTML-escaped inside the HTML body.
    text_context = {
        k: re.sub(r"[\r\n]+", " ", "" if v is None else str(v)) for k, v in context.items()
    }
    html_context = {
        k: (v if k.endswith("_html") else html.escape(v, quote=True)) for k, v in text_context.items()
    }
    subject_context = {
        k: (re.sub(r"<[^>]+>", " ", v).strip() if k.endswith("_html") else v) for k, v in text_context.items()
    }
    subject = Template(subject_tpl).safe_substitute(subject_context)
    html_body = Template(html_tpl).safe_substitute(html_context)
    if row is not None and row.logo_url and str(row.logo_url).startswith("https://"):
        logo = html.escape(str(row.logo_url), quote=True)
        html_body = f'<p><img src="{logo}" alt="Company logo" style="max-height:56px;max-width:220px"></p>{html_body}'
    if row is not None and row.signature_html:
        html_body = f'{html_body}<div style="margin-top:24px">{row.signature_html}</div>'
    return RenderedTemplate(subject=subject, html_body=html_body)


# Backwards-compatible name used by older imports.
_DEFAULT_TEMPLATES = DEFAULT_TEMPLATES
