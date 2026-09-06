from string import Template

from app.services.document_intake.template_renderer import _DEFAULT_TEMPLATES, render_template


def test_default_templates_exist_for_all_rejection_reasons():
    expected_keys = {"domain_rejected", "no_attachment", "invalid_file_type", "encrypted_file", "success", "failure"}
    assert expected_keys.issubset(_DEFAULT_TEMPLATES.keys())


def test_render_template_falls_back_to_in_code_default_without_db(db_session):
    rendered = render_template(
        db_session, "domain_rejected",
        context={"subject": "Invoice Submission", "domain": "notallowed.com"},
        integration_id=None,
    )
    assert "Invoice Submission" in rendered.subject
    assert "not authorised" in rendered.html_body


def test_render_template_substitutes_files_placeholder(db_session):
    rendered = render_template(
        db_session, "encrypted_file",
        context={"subject": "Docs", "files": "secret.pdf, secret2.docx"},
        integration_id=None,
    )
    assert "secret.pdf, secret2.docx" in rendered.html_body


def test_render_terminal_templates(db_session):
    success = render_template(db_session, "success", {"subject": "Docs", "batch_no": "CRS-PROD-20260905-000001"})
    failure = render_template(db_session, "failure", {"subject": "Docs", "reason": "PDF conversion failed"})
    assert "CRS-PROD-20260905-000001" in success.html_body
    assert "PDF conversion failed" in failure.html_body
