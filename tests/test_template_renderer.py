from app.models.document_intake import EmailTemplate
from app.services.document_intake.template_renderer import (
    DEFAULT_TEMPLATES, file_list_html, render_template, seed_default_templates,
)


def test_a_template_exists_for_every_rule():
    assert list(DEFAULT_TEMPLATES) == [
        "domain_rejected", "acknowledgement", "no_attachment",
        "invalid_file_type", "invalid_attachments", "success",
    ]


def test_domain_rejected_says_domain_not_valid(db_session):
    rendered = render_template(db_session, "domain_rejected", {"subject": "Invoice", "domain": "notallowed.com"})
    assert "Invoice" in rendered.subject
    assert "notallowed.com" in rendered.html_body and "not valid" in rendered.html_body


def test_acknowledgement_promises_status_shortly(db_session):
    rendered = render_template(db_session, "acknowledgement", {"subject": "Docs", "batch_no": "CLM-1"})
    assert "Greetings" in rendered.html_body and "status shortly" in rendered.html_body and "CLM-1" in rendered.html_body


def test_success_lists_the_attachments(db_session):
    rendered = render_template(db_session, "success", {
        "subject": "Docs", "batch_no": "CLM-1",
        "file_list_html": file_list_html([("invoice.pdf", None), ("scan.tiff", None)]),
    })
    assert "processed successfully" in rendered.html_body
    assert "<li><strong>invoice.pdf</strong></li>" in rendered.html_body
    assert "scan.tiff" in rendered.html_body and "invoice.pdf" not in rendered.subject


def test_invalid_attachments_lists_files_with_reasons(db_session):
    rendered = render_template(db_session, "invalid_attachments", {
        "subject": "Docs", "batch_no": "CLM-1",
        "file_list_html": file_list_html([("secret.pdf", "The PDF is password-protected")]),
    })
    assert "secret.pdf" in rendered.html_body and "password-protected" in rendered.html_body


def test_seeding_upgrades_untouched_old_texts_but_keeps_edits(db_session):
    old_success = (
        "Re: $subject — Document Processed",
        "<p>Your document was received and processed successfully.</p>"
        "<p>Batch number: <strong>$batch_no</strong>.</p>"
        "<p><em>This is an automated response — please do not reply.</em></p>",
    )
    db_session.add(EmailTemplate(template_key="success", locale="en",
                                 subject_template=old_success[0], html_body_template=old_success[1]))
    db_session.add(EmailTemplate(template_key="no_attachment", locale="en",
                                 subject_template="Custom", html_body_template="<p>Edited by admin</p>"))
    db_session.commit()

    seed_default_templates(db_session)

    rows = {t.template_key: t for t in db_session.query(EmailTemplate).all()}
    assert rows["success"].html_body_template == DEFAULT_TEMPLATES["success"][1]
    assert rows["no_attachment"].html_body_template == "<p>Edited by admin</p>"
    assert set(rows) == set(DEFAULT_TEMPLATES)
