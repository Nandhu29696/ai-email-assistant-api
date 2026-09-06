"""
seed_data.py — Populate the database with:
  • admin user     (username: admin,    password: admin123)
  • employee user  (username: employee, password: emp123)
  • lookup reference rows (sentiments, priorities, categories)
  • 10 sample emails with AI analysis

Run from the backend/ directory:
    python scripts/seed_data.py
"""

import sys
import os
from datetime import datetime, timedelta

# Make app importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import SessionLocal, engine, Base
from app.models import (
    Email, EmailAnalysis, SentimentOption, PriorityOption,
    CategoryOption, AllowedDomain,
)
from app.models.user import User
from app.routers.auth import hash_password

# ── Create all tables ─────────────────────────────────────────
Base.metadata.create_all(bind=engine)

db = SessionLocal()

# ── Helper ────────────────────────────────────────────────────
def exists(model, **kwargs):
    return db.query(model).filter_by(**kwargs).first() is not None


try:
    # ── 1. Users ─────────────────────────────────────────────
    if not exists(User, username="admin"):
        db.add(User(
            email="admin@mailai.local",
            username="admin",
            full_name="System Administrator",
            hashed_password=hash_password("admin123"),
            role="admin",
            is_active=True,
        ))
        print("✓ Created admin user  (username: admin / password: admin123)")

    if not exists(User, username="employee"):
        db.add(User(
            email="employee@mailai.local",
            username="employee",
            full_name="Demo Employee",
            hashed_password=hash_password("emp123"),
            role="employee",
            is_active=True,
        ))
        print("✓ Created employee user  (username: employee / password: emp123)")

    # ── 2. Lookup tables ──────────────────────────────────────
    sentiments = [
        ("positive", "Positive", "text-green-600",  1),
        ("neutral",  "Neutral",  "text-slate-500",  2),
        ("negative", "Negative", "text-red-600",    3),
    ]
    for value, label, color, sort in sentiments:
        if not exists(SentimentOption, value=value):
            db.add(SentimentOption(value=value, label=label, color=color, sort_order=sort))

    priorities = [
        ("critical", "Critical", "text-red-700",    4, 1),
        ("high",     "High",     "text-orange-600", 3, 2),
        ("medium",   "Medium",   "text-yellow-600", 2, 3),
        ("low",      "Low",      "text-green-600",  1, 4),
    ]
    for value, label, color, score, sort in priorities:
        if not exists(PriorityOption, value=value):
            db.add(PriorityOption(value=value, label=label, color=color, score=score, sort_order=sort))

    categories = [
        ("complaint",  "Complaint",  "Customer complaints",       1),
        ("support",    "Support",    "Technical or product help", 2),
        ("sales",      "Sales",      "Sales enquiries",           3),
        ("refund",     "Refund",     "Refund requests",           4),
        ("invoice",    "Invoice",    "Billing & invoices",        5),
        ("feedback",   "Feedback",   "General feedback",          6),
        ("general",    "General",    "Miscellaneous",             7),
    ]
    for value, label, desc, sort in categories:
        if not exists(CategoryOption, value=value):
            db.add(CategoryOption(value=value, label=label, description=desc, sort_order=sort))

    # ── 3. Allowed domains ────────────────────────────────────
    for domain in ("gmail.com", "outlook.com", "mailai.local"):
        if not exists(AllowedDomain, domain=domain):
            db.add(AllowedDomain(domain=domain, is_active=True))

    db.flush()  # get IDs for FK references

    # ── 4. Sample emails + analyses ──────────────────────────
    sample_emails = [
        {
            "subject": "My order has not arrived yet!",
            "sender_name": "Alice Johnson",
            "sender_email": "alice@gmail.com",
            "body_plain": "Hi, I placed order #12345 two weeks ago and it still hasn't arrived. This is extremely frustrating. Please help immediately.",
            "sentiment": "negative", "sentiment_score": -0.82,
            "primary_emotion": "frustration",
            "category": "complaint", "priority": "critical", "priority_score": 4,
            "ai_summary": "Customer frustrated about delayed order #12345, placed 2 weeks ago.",
            "suggested_reply": "Dear Alice, we sincerely apologize for the delay. We are investigating your order #12345 and will update you within 24 hours.",
        },
        {
            "subject": "Thank you for the great service!",
            "sender_name": "Bob Smith",
            "sender_email": "bob@gmail.com",
            "body_plain": "Just wanted to say that your support team was absolutely fantastic. The issue was resolved within minutes. Keep it up!",
            "sentiment": "positive", "sentiment_score": 0.91,
            "primary_emotion": "satisfaction",
            "category": "feedback", "priority": "low", "priority_score": 1,
            "ai_summary": "Customer praising support team for fast issue resolution.",
            "suggested_reply": "Thank you so much for your kind words, Bob! We'll share your feedback with the team.",
        },
        {
            "subject": "Request for invoice #INV-2024-089",
            "sender_name": "Carol White",
            "sender_email": "carol@outlook.com",
            "body_plain": "Hello, could you please resend invoice #INV-2024-089? I can't find it in my inbox.",
            "sentiment": "neutral", "sentiment_score": 0.05,
            "primary_emotion": "neutral",
            "category": "invoice", "priority": "medium", "priority_score": 2,
            "ai_summary": "Customer requesting re-send of invoice INV-2024-089.",
            "suggested_reply": "Hi Carol, please find invoice #INV-2024-089 attached. Let us know if you need anything else.",
        },
        {
            "subject": "Product not working as described",
            "sender_name": "David Lee",
            "sender_email": "david@gmail.com",
            "body_plain": "I purchased your software last week and it keeps crashing on startup. Very disappointed. I want a refund.",
            "sentiment": "negative", "sentiment_score": -0.74,
            "primary_emotion": "anger",
            "category": "refund", "priority": "high", "priority_score": 3,
            "ai_summary": "Customer requesting refund; software crashes on startup.",
            "suggested_reply": "Hi David, we're sorry to hear this. Please share your OS version and we'll fix it immediately or process a full refund.",
        },
        {
            "subject": "Interested in your enterprise plan",
            "sender_name": "Eve Martinez",
            "sender_email": "eve@outlook.com",
            "body_plain": "Hi, our company has 50 employees and we are looking for an enterprise email solution. Could you send me pricing details?",
            "sentiment": "positive", "sentiment_score": 0.55,
            "primary_emotion": "excitement",
            "category": "sales", "priority": "high", "priority_score": 3,
            "ai_summary": "Enterprise prospect with 50 employees requesting pricing.",
            "suggested_reply": "Hi Eve, thank you for your interest! Our enterprise plan starts at $15/user/month. I'll have our sales team reach out shortly.",
        },
        {
            "subject": "How do I reset my password?",
            "sender_name": "Frank Brown",
            "sender_email": "frank@gmail.com",
            "body_plain": "I forgot my password and can't log in. The reset email isn't arriving either. Please help.",
            "sentiment": "neutral", "sentiment_score": -0.15,
            "primary_emotion": "concern",
            "category": "support", "priority": "medium", "priority_score": 2,
            "ai_summary": "User unable to log in; password reset email not received.",
            "suggested_reply": "Hi Frank, please try checking your spam folder. If still no email, contact support@mailai.com with your username.",
        },
        {
            "subject": "Urgent: Server outage affecting production",
            "sender_name": "Grace Kim",
            "sender_email": "grace@outlook.com",
            "body_plain": "URGENT: Our production server is down and we believe it's related to your API. This is causing major revenue loss. Need immediate help!",
            "sentiment": "negative", "sentiment_score": -0.95,
            "primary_emotion": "urgency",
            "category": "support", "priority": "critical", "priority_score": 4,
            "ai_summary": "Production outage; customer blames API for server downtime.",
            "suggested_reply": "Grace, we are treating this as P1. Our on-call engineer will contact you within 15 minutes.",
        },
        {
            "subject": "Feature request: dark mode",
            "sender_name": "Henry Wilson",
            "sender_email": "henry@gmail.com",
            "body_plain": "Love the product! One suggestion though — it would be great if you added a dark mode option.",
            "sentiment": "positive", "sentiment_score": 0.72,
            "primary_emotion": "satisfaction",
            "category": "feedback", "priority": "low", "priority_score": 1,
            "ai_summary": "Customer requesting dark mode feature.",
            "suggested_reply": "Hi Henry, great idea! Dark mode is on our roadmap for Q3. Thanks for the suggestion!",
        },
        {
            "subject": "Billing discrepancy on my account",
            "sender_name": "Iris Chen",
            "sender_email": "iris@gmail.com",
            "body_plain": "I was charged $150 but my plan only costs $99/month. Please check and refund the difference ASAP.",
            "sentiment": "negative", "sentiment_score": -0.61,
            "primary_emotion": "frustration",
            "category": "invoice", "priority": "high", "priority_score": 3,
            "ai_summary": "Customer overcharged by $51; requesting refund.",
            "suggested_reply": "Hi Iris, we apologize for the billing error. We have identified the issue and will refund $51 within 3-5 business days.",
        },
        {
            "subject": "General inquiry about your services",
            "sender_name": "Jack Davis",
            "sender_email": "jack@outlook.com",
            "body_plain": "Hello, I came across your company online and wanted to learn more about what services you offer.",
            "sentiment": "neutral", "sentiment_score": 0.10,
            "primary_emotion": "neutral",
            "category": "general", "priority": "low", "priority_score": 1,
            "ai_summary": "General inquiry from potential customer about services.",
            "suggested_reply": "Hi Jack, thanks for reaching out! We offer AI-powered email management. I'd love to schedule a 15-minute demo — does next week work?",
        },
    ]

    for i, data in enumerate(sample_emails):
        msg_id = f"seed-msg-{i+1:03d}@mailai.local"
        if exists(Email, message_id=msg_id):
            continue

        email = Email(
            message_id=msg_id,
            subject=data["subject"],
            sender_name=data["sender_name"],
            sender_email=data["sender_email"],
            recipient_email="inbox@mailai.local",
            body_plain=data["body_plain"],
            body_clean=data["body_plain"],
            received_at=datetime.utcnow() - timedelta(hours=i * 3),
            processed_at=datetime.utcnow() - timedelta(hours=i * 3 - 1),
            is_read=i % 3 == 0,
            is_archived=False,
        )
        db.add(email)
        db.flush()  # get email.id

        analysis = EmailAnalysis(
            email_id=email.id,
            sentiment=data["sentiment"],
            sentiment_score=data["sentiment_score"],
            primary_emotion=data["primary_emotion"],
            emotions_json=[{"emotion": data["primary_emotion"], "score": abs(data["sentiment_score"])}],
            category=data["category"],
            category_confidence=0.88,
            priority=data["priority"],
            priority_score=data["priority_score"],
            ai_summary=data["ai_summary"],
            suggested_reply=data["suggested_reply"],
            routed_to="support" if data["category"] in ("support", "complaint") else "general",
            routing_reason="Auto-routed by AI",
            model_version="seed-v1.0",
            processing_time_ms=120 + i * 10,
        )
        db.add(analysis)

    db.commit()
    print("✓ Inserted lookup data (sentiments, priorities, categories, domains)")
    print("✓ Inserted 10 sample emails with AI analysis")
    print()
    print("═" * 50)
    print("  CREDENTIALS")
    print("  Admin    → username: admin     | password: admin123")
    print("  Employee → username: employee  | password: emp123")
    print("═" * 50)

except Exception as exc:
    db.rollback()
    raise exc
finally:
    db.close()
