from app.services.preprocessor import preprocess_email, strip_html
from app.services.sentiment_analyzer import analyze_sentiment
from app.services.emotion_detector import detect_emotions
from app.services.classifier import _keyword_classify


def test_strip_html():
    raw_html = "<html><body><h1>Hello</h1><p>This is a <b>test</b> email.</p></body></html>"
    text = strip_html(raw_html)
    assert "Hello" in text
    assert "test" in text


def test_preprocessor_does_not_strip_body_starting_with_greeting():
    raw_text = (
        "Thank you for contacting our sales team yesterday.\n"
        "We are following up with the requested quote for enterprise licensing.\n"
        "Please let us know if you have any questions.\n\n"
        "Best regards,\nJohn Doe"
    )
    cleaned = preprocess_email(raw_text, None)
    assert "Thank you for contacting our sales team yesterday" in cleaned
    assert "enterprise licensing" in cleaned


def test_sentiment_analysis_positive_negative_neutral():
    pos = analyze_sentiment("Thank you so much, this software is fantastic and resolved all our issues!")
    assert pos.label == "positive"
    assert pos.score > 0.05

    neg = analyze_sentiment("I am extremely frustrated! Your service is broken and unacceptable!")
    assert neg.label == "negative"
    assert neg.score < -0.05

    neu = analyze_sentiment("The status meeting is scheduled for Tuesday at 10 AM.")
    assert neu.label == "neutral"


def test_emotion_detection():
    emotions = detect_emotions("I am furious about this unexpected charge and need an answer ASAP!")
    assert emotions.primary_emotion in ("anger", "urgency", "concern")
    assert len(emotions.emotions) > 0


def test_keyword_classification():
    result = _keyword_classify("Can you send me the invoice and billing details for last month?")
    assert result is not None
    assert result.category == "invoice"
