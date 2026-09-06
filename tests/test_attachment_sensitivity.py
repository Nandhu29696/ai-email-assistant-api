import io

from app.services.document_intake.sensitive_data_detector import extract_attachment_text


def test_extract_attachment_text_from_pdf():
    reportlab = __import__("pytest").importorskip("reportlab")
    from reportlab.pdfgen import canvas
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer)
    pdf.drawString(72, 720, "Account number 123-45-6789")
    pdf.save()

    text = extract_attachment_text("statement.pdf", buffer.getvalue())
    assert "123-45-6789" in text


def test_extract_attachment_text_from_docx():
    import zipfile
    from xml.sax.saxutils import escape

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "word/document.xml",
            f"<document><body><p>{escape('Patient SSN 123-45-6789')}</p></body></document>",
        )

    text = extract_attachment_text("record.docx", buffer.getvalue())
    assert "123-45-6789" in text


def test_tiff_text_extraction_is_safe_without_ocr():
    assert extract_attachment_text("scan.tiff", b"not-ocr-processed") == ""
