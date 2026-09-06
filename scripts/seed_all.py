"""
seed_all.py — Full database seed covering every table.

Tables populated:
  users, user_sessions, audit_logs, api_request_logs,
  email_integrations, emails, email_analyses, notifications,
  email_replies, email_response_tracker,
  sentiment_options, priority_options, category_options, allowed_domains

Usage (from backend/ directory):
    python scripts/seed_all.py
    python scripts/seed_all.py --reset   # drops & recreates everything first
"""

import sys
import os
import random
import secrets
import argparse
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import SessionLocal, engine, Base
from app.models.email import (
    Email, EmailAnalysis, EmailIntegration, Notification,
    EmailReply, EmailResponseTracker,
    SentimentOption, PriorityOption, CategoryOption, AllowedDomain,
)
from app.models.user import User, UserSession, AuditLog, ApiRequestLog
from app.routers.auth import hash_password

# ── CLI ───────────────────────────────────────────────────────
parser = argparse.ArgumentParser()
parser.add_argument("--reset", action="store_true", help="Drop and recreate all tables before seeding")
args = parser.parse_args()

if args.reset:
    print("⚠  Dropping all tables…")
    Base.metadata.drop_all(bind=engine)
    print("✓  Tables dropped.")

Base.metadata.create_all(bind=engine)
db = SessionLocal()

def now() -> datetime:
    return datetime.now(timezone.utc)

def ago(**kw) -> datetime:
    return now() - timedelta(**kw)

def exists(model, **kw):
    return db.query(model).filter_by(**kw).first()

def p(msg): print(f"  {msg}")


# ══════════════════════════════════════════════════════════════
# 1. LOOKUP TABLES
# ══════════════════════════════════════════════════════════════
print("\n── 1. Lookup tables ──────────────────────────────────")

if not exists(SentimentOption, value="positive"):
    db.bulk_insert_mappings(SentimentOption, [
        {"value": "positive", "label": "Positive", "color": "green",  "sort_order": 1},
        {"value": "neutral",  "label": "Neutral",  "color": "gray",   "sort_order": 2},
        {"value": "negative", "label": "Negative", "color": "red",    "sort_order": 3},
    ])
    p("Sentiment options seeded")

if not exists(PriorityOption, value="critical"):
    db.bulk_insert_mappings(PriorityOption, [
        {"value": "critical", "label": "Critical", "color": "red",    "score": 4, "sort_order": 1},
        {"value": "high",     "label": "High",     "color": "orange", "score": 3, "sort_order": 2},
        {"value": "medium",   "label": "Medium",   "color": "yellow", "score": 2, "sort_order": 3},
        {"value": "low",      "label": "Low",      "color": "blue",   "score": 1, "sort_order": 4},
    ])
    p("Priority options seeded")

if not exists(CategoryOption, value="complaint"):
    db.bulk_insert_mappings(CategoryOption, [
        {"value": "complaint", "label": "Complaint", "description": "Customer complaints",        "sort_order": 1},
        {"value": "support",   "label": "Support",   "description": "Technical support",         "sort_order": 2},
        {"value": "sales",     "label": "Sales",     "description": "Sales inquiries",           "sort_order": 3},
        {"value": "refund",    "label": "Refund",    "description": "Refund requests",           "sort_order": 4},
        {"value": "invoice",   "label": "Invoice",   "description": "Billing queries",           "sort_order": 5},
        {"value": "feedback",  "label": "Feedback",  "description": "Product feedback",          "sort_order": 6},
        {"value": "general",   "label": "General",   "description": "General enquiries",         "sort_order": 7},
    ])
    p("Category options seeded")

for domain, notes in [
    ("gmail.com",      "Google Gmail"),
    ("outlook.com",    "Microsoft Outlook"),
    ("hotmail.com",    "Microsoft Hotmail"),
    ("yahoo.com",      "Yahoo Mail"),
    ("icloud.com",     "Apple iCloud"),
    ("protonmail.com", "ProtonMail"),
    ("mailai.local",   "Internal demo domain"),
]:
    if not exists(AllowedDomain, domain=domain):
        db.add(AllowedDomain(domain=domain, is_active=True, notes=notes))

db.commit()
p("Allowed domains seeded")


# ══════════════════════════════════════════════════════════════
# 2. USERS
# ══════════════════════════════════════════════════════════════
print("\n── 2. Users ──────────────────────────────────────────")

USERS_DATA = [
    # (username, email, full_name, password, role, last_login_offset_h)
    ("admin",    "admin@mailai.local",    "System Administrator", "admin123",  "admin",    1),
    ("manager",  "manager@mailai.local",  "Sarah Manager",        "manager123","admin",    3),
    ("alice",    "alice@mailai.local",    "Alice Thompson",       "alice123",  "employee", 2),
    ("bob",      "bob@mailai.local",      "Bob Richards",         "bob123",    "employee", 5),
    ("carol",    "carol@mailai.local",    "Carol Singh",          "carol123",  "employee", 8),
    ("david",    "david@mailai.local",    "David Okafor",         "david123",  "employee", 12),
    ("employee", "employee@mailai.local", "Demo Employee",        "emp123",    "employee", 4),
]

user_objs = {}
for username, email, full_name, password, role, login_h in USERS_DATA:
    u = exists(User, username=username)
    if not u:
        u = User(
            username=username, email=email, full_name=full_name,
            hashed_password=hash_password(password), role=role,
            is_active=True, last_login_at=ago(hours=login_h),
            failed_login_count=0,
        )
        db.add(u)
        db.flush()
        p(f"User created: {username} / {password}  [{role}]")
    else:
        p(f"User exists:  {username}")
    user_objs[username] = u

db.commit()


# ══════════════════════════════════════════════════════════════
# 3. USER SESSIONS
# ══════════════════════════════════════════════════════════════
print("\n── 3. User sessions ──────────────────────────────────")

SESSION_DATA = [
    # (username, ip, ua, hours_ago, is_active)
    ("admin",    "192.168.1.10", "Mozilla/5.0 (Windows NT 10.0; Win64) Chrome/124",  1,  True),
    ("admin",    "10.0.0.5",     "Mozilla/5.0 (Macintosh) Safari/537.36",            24, True),
    ("manager",  "192.168.1.20", "Mozilla/5.0 (Windows NT 10.0) Firefox/125",        3,  True),
    ("alice",    "192.168.1.30", "Mozilla/5.0 (iPhone; CPU iPhone OS 17) Safari",    2,  True),
    ("bob",      "192.168.1.40", "Mozilla/5.0 (Linux; Android 14) Chrome/124",       5,  True),
    ("carol",    "192.168.1.50", "Mozilla/5.0 (Windows NT 10.0) Edge/124",           8,  False),
    ("employee", "172.16.0.5",   "Mozilla/5.0 (Macintosh) Chrome/124",               4,  True),
]

for username, ip, ua, h_ago, active in SESSION_DATA:
    u = user_objs.get(username)
    if not u:
        continue
    token = secrets.token_urlsafe(64)
    db.add(UserSession(
        user_id=u.id, refresh_token=token,
        ip_address=ip, user_agent=ua,
        is_active=active,
        expires_at=ago(hours=h_ago) + timedelta(days=7),
        last_used_at=ago(hours=h_ago),
        revoked_at=None if active else ago(hours=h_ago - 1),
    ))

db.commit()
p(f"{len(SESSION_DATA)} sessions created")


# ══════════════════════════════════════════════════════════════
# 4. AUDIT LOGS
# ══════════════════════════════════════════════════════════════
print("\n── 4. Audit logs ─────────────────────────────────────")

AUDIT_ROWS = [
    # (username, action, resource_type, resource_id, ip, status, hours_ago, details)
    ("admin",    "login",          "user", 1, "192.168.1.10", "success", 1,  {}),
    ("admin",    "user_created",   "user", 3, "192.168.1.10", "success", 2,  {"created_username": "alice", "role": "employee"}),
    ("admin",    "user_created",   "user", 4, "192.168.1.10", "success", 3,  {"created_username": "bob",   "role": "employee"}),
    ("admin",    "user_updated",   "user", 5, "192.168.1.10", "success", 4,  {"role": "employee"}),
    ("admin",    "login",          "user", 1, "10.0.0.5",     "success", 25, {}),
    ("manager",  "login",          "user", 2, "192.168.1.20", "success", 3,  {}),
    ("manager",  "email_viewed",   "email",1, "192.168.1.20", "success", 3,  {}),
    ("manager",  "reply_sent",     "reply",1, "192.168.1.20", "success", 3,  {}),
    ("alice",    "login",          "user", 3, "192.168.1.30", "success", 2,  {}),
    ("alice",    "login_failed",   "user", 3, "192.168.1.30", "failure", 3,  {"attempt": 1}),
    ("alice",    "email_viewed",   "email",2, "192.168.1.30", "success", 2,  {}),
    ("alice",    "reply_drafted",  "reply",2, "192.168.1.30", "success", 2,  {}),
    ("bob",      "login",          "user", 4, "192.168.1.40", "success", 5,  {}),
    ("bob",      "email_archived", "email",3, "192.168.1.40", "success", 5,  {}),
    ("carol",    "login",          "user", 5, "192.168.1.50", "success", 8,  {}),
    ("carol",    "login_failed",   "user", 5, "192.168.1.50", "failure", 9,  {"attempt": 1}),
    ("carol",    "login_failed",   "user", 5, "192.168.1.50", "failure", 9,  {"attempt": 2}),
    ("carol",    "logout",         "user", 5, "192.168.1.50", "success", 7,  {}),
    ("employee", "login",          "user", 7, "172.16.0.5",   "success", 4,  {}),
    ("employee", "password_changed","user",7, "172.16.0.5",   "success", 4,  {}),
    ("admin",    "session_revoked","user", 5, "192.168.1.10", "success", 0,  {"session_id": 6}),
    (None,       "login_failed",   "user",None,"203.0.113.42","failure", 0,  {"reason": "unknown_user", "username": "root"}),
    (None,       "login_failed",   "user",None,"203.0.113.42","failure", 0,  {"reason": "unknown_user", "username": "admin"}),
]

admin_id    = user_objs["admin"].id
manager_id  = user_objs["manager"].id

for row in AUDIT_ROWS:
    username, action, rtype, rid, ip, status, h_ago, details = row
    uid = user_objs[username].id if username else None
    db.add(AuditLog(
        user_id=uid, action=action, resource_type=rtype,
        resource_id=rid, ip_address=ip, user_agent="Mozilla/5.0 (seed)",
        status=status, details=details,
        created_at=ago(hours=h_ago),
    ))

db.commit()
p(f"{len(AUDIT_ROWS)} audit log entries created")


# ══════════════════════════════════════════════════════════════
# 5. API REQUEST LOGS
# ══════════════════════════════════════════════════════════════
print("\n── 5. API request logs ───────────────────────────────")

API_LOG_TEMPLATES = [
    # (method, path, status_code, ms, user_key)
    ("GET",    "/api/dashboard/stats",      200,  45,  "admin"),
    ("GET",    "/api/emails",               200,  78,  "alice"),
    ("GET",    "/api/emails/1",             200,  32,  "alice"),
    ("POST",   "/api/emails/1/analyze",     202,  5,   "alice"),
    ("GET",    "/api/dashboard/trends",     200,  120, "manager"),
    ("GET",    "/api/reply-tracker",        200,  88,  "manager"),
    ("PATCH",  "/api/emails/1",             200,  28,  "bob"),
    ("GET",    "/api/logs/audit",           200,  95,  "admin"),
    ("GET",    "/api/logs/requests",        200,  110, "admin"),
    ("GET",    "/api/admin/users",          200,  42,  "admin"),
    ("POST",   "/api/auth/login",           200,  220, None),
    ("POST",   "/api/auth/login",           401,  15,  None),
    ("POST",   "/api/auth/refresh",         200,  35,  None),
    ("GET",    "/api/emails/999",           404,  12,  "alice"),
    ("POST",   "/api/emails/2/replies",     201,  88,  "carol"),
    ("GET",    "/api/integrations",         200,  55,  "admin"),
    ("GET",    "/api/lookups/priorities",   200,  18,  "bob"),
    ("GET",    "/api/dashboard/stats",      200,  48,  "manager"),
    ("DELETE", "/api/admin/users/5",        200,  35,  "admin"),
    ("GET",    "/api/reply-tracker/summary",200,  95,  "manager"),
    ("PATCH",  "/api/reply-tracker/3",      200,  40,  "carol"),
    ("POST",   "/api/reply-tracker/sync",   200,  310, "admin"),
    ("GET",    "/api/emails",               200,  82,  "david"),
    ("GET",    "/api/logs/summary",         200,  140, "admin"),
    ("POST",   "/api/auth/login",           403,  18,  None),   # locked account attempt
    ("GET",    "/api/domains",              200,  22,  "admin"),
    ("POST",   "/api/domains",              201,  30,  "admin"),
    ("GET",    "/api/emails",               500,  8,   "alice"),  # simulated server error
    ("GET",    "/api/dashboard/stats",      200,  51,  "carol"),
    ("GET",    "/api/admin/system-stats",   200,  65,  "admin"),
]

for i, (method, path, sc, ms, ukey) in enumerate(API_LOG_TEMPLATES * 3):  # repeat 3x for volume
    uid = user_objs[ukey].id if ukey else None
    db.add(ApiRequestLog(
        user_id=uid, method=method, path=path,
        query_params="page=1" if "emails" in path else None,
        status_code=sc, response_time_ms=ms + random.randint(-10, 30),
        ip_address=f"192.168.1.{random.randint(1, 100)}",
        user_agent="Mozilla/5.0 (seed-runner)",
        error_detail="Internal server error" if sc == 500 else None,
        created_at=ago(minutes=i * 4 + random.randint(0, 3)),
    ))

db.commit()
p(f"{len(API_LOG_TEMPLATES) * 3} API request log entries created")


# ══════════════════════════════════════════════════════════════
# 6. EMAIL INTEGRATIONS
# ══════════════════════════════════════════════════════════════
print("\n── 6. Email integrations ─────────────────────────────")

INTEGRATIONS = [
    ("gmail",   "support@mailai.local",  True,  ago(days=30)),
    ("gmail",   "sales@mailai.local",    True,  ago(days=20)),
    ("outlook", "billing@mailai.local",  True,  ago(days=15)),
    ("gmail",   "admin@mailai.local",    False, ago(days=60)),
]

integration_objs = []
for provider, addr, active, created in INTEGRATIONS:
    integ = exists(EmailIntegration, email_address=addr)
    if not integ:
        integ = EmailIntegration(
            provider=provider, email_address=addr,
            access_token=f"ya29.seed_access_{secrets.token_hex(8)}",
            refresh_token=f"1//seed_refresh_{secrets.token_hex(8)}",
            token_expiry=ago(hours=-2),   # expires 2h from now
            is_active=active,
            created_at=created,
        )
        db.add(integ)
        db.flush()
        p(f"Integration: {provider} / {addr}")
    integration_objs.append(integ)

db.commit()


# ══════════════════════════════════════════════════════════════
# 7. EMAILS + ANALYSES + REPLIES + TRACKER + NOTIFICATIONS
# ══════════════════════════════════════════════════════════════
print("\n── 7. Emails, analyses, replies, tracker, notifications")

EMAILS = [
    # fmt: (subject, sender_name, sender_email, body, sentiment, score, emotion,
    #        category, priority, p_score, summary, reply_text,
    #        is_read, hours_ago, reply_status, sla_breach)
    (
        "My order #12345 has not arrived after 3 weeks!",
        "Alice Johnson", "alice.j@gmail.com",
        "I placed order #12345 three weeks ago and it still hasn't arrived. This is completely unacceptable! I demand a full refund or immediate shipment.",
        "negative", -0.91, "anger",
        "complaint", "critical", 4,
        "Customer extremely angry about 3-week delayed order #12345. Threatening refund.",
        "Dear Alice, we sincerely apologize. Your order #12345 was held at customs. We are dispatching a replacement with express shipping at no charge.",
        True, 2, "replied", False,
    ),
    (
        "Fantastic experience with your support team!",
        "Bob Smith", "bob.smith@gmail.com",
        "Just wanted to say a huge thank you! Your agent Sarah resolved my issue in under 10 minutes. Absolutely amazing service. Will recommend to everyone!",
        "positive", 0.94, "satisfaction",
        "feedback", "low", 1,
        "Customer praising support agent Sarah for fast resolution.",
        "Thank you so much, Bob! We will definitely share your feedback with Sarah and the team. We truly appreciate it!",
        True, 5, "replied", False,
    ),
    (
        "Re: Invoice INV-2024-089 missing from portal",
        "Carol White", "carol.white@outlook.com",
        "Hi, invoice INV-2024-089 from last month is not showing up in my billing portal. Could you resend it as a PDF? I need it for my accounts.",
        "neutral", 0.05, "neutral",
        "invoice", "medium", 2,
        "Invoice INV-2024-089 missing from customer portal. Customer needs PDF.",
        "Hi Carol, please find invoice INV-2024-089 attached as a PDF. We have also fixed the portal display issue. Sorry for the inconvenience!",
        True, 8, "replied", False,
    ),
    (
        "Software crashes on Windows 11 — need refund",
        "David Lee", "david.l@gmail.com",
        "Your software crashes every time on Windows 11 startup. I've tried reinstalling three times. This is unacceptable. I want a full refund immediately.",
        "negative", -0.78, "frustration",
        "refund", "high", 3,
        "Software crash on Windows 11. Customer demanding full refund after 3 reinstall attempts.",
        "Hi David, we are very sorry. We identified a Windows 11 compatibility issue in v2.1. Please try v2.2 at [link]. If still crashing, we'll process your full refund immediately.",
        False, 1, "pending", False,
    ),
    (
        "Enterprise plan enquiry — 200 users",
        "Eve Martinez", "eve.m@outlook.com",
        "Hello, our company is evaluating email management tools for 200 users. Could you share enterprise pricing, SLA guarantees, and GDPR compliance info?",
        "positive", 0.62, "excitement",
        "sales", "high", 3,
        "Hot enterprise lead: 200 users, needs pricing + SLA + GDPR info.",
        "Hi Eve, thank you for your interest! Enterprise pricing starts at $12/user/month with 99.9% SLA uptime guarantee and full GDPR compliance. I'll have our sales team reach out today.",
        False, 3, "pending", False,
    ),
    (
        "Password reset email never arrives",
        "Frank Brown", "frankb@gmail.com",
        "Hi, I've tried resetting my password 4 times now and the reset email never arrives. Checked spam too. My username is frankb. Please help ASAP.",
        "negative", -0.42, "concern",
        "support", "medium", 2,
        "User locked out; password reset emails not delivered. Username: frankb.",
        "Hi Frank, we found the issue — your email was incorrectly flagged by our spam filter. We've manually reset your password to TempPass#2024 — please change it immediately after login.",
        True, 6, "replied", False,
    ),
    (
        "URGENT: Production API returning 503 errors",
        "Grace Kim", "grace.kim@outlook.com",
        "CRITICAL: Your API has been returning 503 errors for the past 45 minutes. Our entire production pipeline is down. We are losing $5000/minute. This needs immediate attention!",
        "negative", -0.98, "urgency",
        "support", "critical", 4,
        "Production outage: API 503 errors for 45+ minutes, $5K/min revenue loss.",
        "Grace, this is our P0. The engineering team has been paged. Root cause: Redis failover issue now resolved. Services restored as of 14:32 UTC. Post-mortem report follows within 2 hours.",
        True, 12, "replied", False,
    ),
    (
        "Feature request: Bulk email export to CSV",
        "Henry Wilson", "hwilson@gmail.com",
        "Love the product! Would be very helpful if we could export emails in bulk to CSV for reporting. Is this planned?",
        "positive", 0.68, "satisfaction",
        "feedback", "low", 1,
        "Feature request: bulk email CSV export for reporting purposes.",
        "Hi Henry! Great suggestion — bulk CSV export is already in our Q3 roadmap. You'll get early access as a valued customer. Stay tuned!",
        True, 20, "replied", False,
    ),
    (
        "Charged twice for last month subscription",
        "Iris Chen", "iris.chen@gmail.com",
        "I was charged $99 twice on April 15th. My bank statement shows two identical charges. Please refund one immediately. Transaction IDs: TXN-8821, TXN-8822.",
        "negative", -0.67, "frustration",
        "invoice", "high", 3,
        "Duplicate charge of $99 on April 15. Transaction IDs: TXN-8821, TXN-8822.",
        "Hi Iris, we confirmed the duplicate charge. TXN-8822 has been refunded. You'll see it in 3-5 business days. We've also added a $10 credit to your account for the inconvenience.",
        True, 15, "replied", False,
    ),
    (
        "General service enquiry",
        "Jack Davis", "jdavis@outlook.com",
        "Hello, I came across your company and would like to know more about your email AI services and pricing.",
        "neutral", 0.10, "neutral",
        "general", "low", 1,
        "General prospect enquiry about services and pricing.",
        "Hi Jack! We offer AI-powered email triage, sentiment analysis, and smart replies. Plans start at $29/month. I'll send you a full brochure and schedule a 20-minute demo — when works for you?",
        False, 25, "pending", False,
    ),
    (
        "Account suspended without warning",
        "Karen Taylor", "karen.t@gmail.com",
        "My account was suspended this morning without any notice or explanation. I have an active subscription until December. This is completely unacceptable!",
        "negative", -0.88, "anger",
        "complaint", "critical", 4,
        "Account incorrectly suspended. Active subscription until December.",
        "Dear Karen, we sincerely apologize. Your account was suspended in error due to an automated billing flag. Your account is now fully reinstated with 2 weeks added at no charge.",
        False, 0, "escalated", True,
    ),
    (
        "Looking to upgrade from Starter to Pro",
        "Liam O'Brien", "liamob@gmail.com",
        "Hi, I've been on the Starter plan for 6 months and love it. Ready to upgrade to Pro. What are the benefits and how do I switch?",
        "positive", 0.75, "excitement",
        "sales", "medium", 2,
        "Existing customer wants to upgrade from Starter to Pro plan.",
        "Hi Liam! Upgrading to Pro gives you: unlimited emails, priority support, advanced analytics, and API access. Simply go to Account → Billing → Upgrade. As a loyalty bonus, your first Pro month is on us!",
        True, 30, "replied", False,
    ),
    (
        "Integration with Salesforce not working",
        "Maya Patel", "maya.p@outlook.com",
        "The Salesforce integration stopped syncing emails 2 days ago. Our sales team is missing critical follow-up data. Please advise urgently.",
        "negative", -0.65, "concern",
        "support", "high", 3,
        "Salesforce integration broken for 2 days, sales team impacted.",
        "Hi Maya, we identified a certificate expiry issue with the Salesforce connector. Please go to Integrations > Salesforce > Reconnect and authorize again. Should resolve immediately.",
        False, 4, "pending", True,
    ),
    (
        "Great product, minor UX feedback",
        "Nathan Brooks", "nbrooks@gmail.com",
        "Overall very happy with the platform! One small thing — the inbox filter resets every time I navigate away. Would be nice if it persisted.",
        "positive", 0.60, "satisfaction",
        "feedback", "low", 1,
        "UX feedback: inbox filter should persist between page navigations.",
        "Thanks for the feedback, Nathan! You're right — persistent filters are a quick win. We'll ship that in the next release, targeted for next week.",
        True, 48, "replied", False,
    ),
    (
        "Cannot download attachment from email",
        "Olivia Scott", "oscott@icloud.com",
        "When I click to download an attachment, nothing happens. The file is supposed to be a PDF. Browser is Chrome 124 on Windows 11. Have tried refreshing.",
        "negative", -0.38, "concern",
        "support", "medium", 2,
        "PDF attachment download broken in Chrome 124/Windows 11.",
        "Hi Olivia, this was a Chrome 124 extension conflict. Please try in Incognito mode or Firefox. We've also pushed a hotfix — try again in 30 minutes.",
        True, 7, "replied", False,
    ),
    (
        "Annual plan renewal quote needed",
        "Peter Evans", "pevans@outlook.com",
        "Hi, our annual subscription renews next month. Could you send us a quote for renewal, including any discounts for multi-year commitment?",
        "neutral", 0.20, "neutral",
        "invoice", "medium", 2,
        "Annual renewal quote request. Interest in multi-year discount.",
        "Hi Peter, your renewal is due on July 15. We're offering: 1 year at current rate, 2 years at 10% off, 3 years at 18% off. I'll send a formal quote to your billing email shortly.",
        True, 36, "replied", False,
    ),
    (
        "Team training request for new employees",
        "Quinn Foster", "qfoster@gmail.com",
        "We have 8 new employees joining next month who will use your platform. Is there a training programme or onboarding guide available?",
        "positive", 0.55, "excitement",
        "support", "low", 1,
        "Onboarding training requested for 8 new employees.",
        "Hi Quinn! We offer a free onboarding webinar every Tuesday at 2pm UTC, plus a self-paced video library. I'll enroll your new starters and send calendar invites. Welcome to the family!",
        False, 18, "pending", False,
    ),
    (
        "Data export for GDPR compliance audit",
        "Rachel Hughes", "rhughes@protonmail.com",
        "We are undergoing a GDPR compliance audit and need to export all data associated with our account within the next 5 business days. How do we proceed?",
        "neutral", -0.12, "concern",
        "general", "high", 3,
        "GDPR data export request with 5-business-day deadline.",
        "Hi Rachel, you can request your full data export under Account → Privacy → Export Data. Processing takes up to 24 hours. For audit certification, email compliance@mailai.com.",
        True, 10, "replied", False,
    ),
    (
        "API rate limit hit — 429 errors",
        "Samuel Green", "sgreen@outlook.com",
        "Our integration is hitting 429 rate limit errors. We send about 500 emails/hour. Is there an enterprise tier with higher limits? Very urgent.",
        "negative", -0.50, "urgency",
        "support", "high", 3,
        "API rate limit (429) errors at 500 emails/hour volume. Needs enterprise tier.",
        "Hi Samuel, your current plan allows 200 calls/hour. Enterprise tier offers 5000/hour. I've temporarily raised your limit to 1000/hour while we sort the upgrade. Expect a quote within the hour.",
        False, 2, "pending", True,
    ),
    (
        "Thank you — 5 star service!",
        "Tina Ross", "tinaross@gmail.com",
        "Wow! From signup to setup took only 15 minutes. The AI analysis is incredibly accurate and has already saved our team hours. A genuine 5-star product!",
        "positive", 0.97, "excitement",
        "feedback", "low", 1,
        "5-star unsolicited review. Extremely satisfied new customer.",
        "Tina, this made our entire team's day! We'll share your wonderful feedback. As a thank you, we've upgraded your account to Pro for 3 months — on us!",
        True, 40, "replied", False,
    ),
    (
        "Phishing email received via your platform",
        "Uma Sharma", "uma.s@gmail.com",
        "I received what appears to be a phishing email through your platform claiming to be from your billing department asking for card details. I haven't clicked anything. Please investigate.",
        "negative", -0.72, "concern",
        "complaint", "critical", 4,
        "Phishing attempt reported via platform. Security investigation required.",
        "Uma, thank you for reporting this immediately! Our security team is investigating. The sender account has been suspended. We confirm we never ask for card details by email. Please ignore and delete.",
        True, 3, "escalated", False,
    ),
    (
        "Mobile app login not working",
        "Victor Ngozi", "vngozi@yahoo.com",
        "The iOS app keeps saying 'invalid credentials' even though I can log in fine on the website. Using iPhone 15 Pro, iOS 17.4.",
        "negative", -0.45, "frustration",
        "support", "medium", 2,
        "iOS app login failure on iPhone 15 Pro / iOS 17.4. Web login works.",
        "Hi Victor, this is a known issue with iOS 17.4 and our app v3.1. Please update the app to v3.2 from the App Store. If still failing, delete and reinstall. Sorry for the hassle!",
        False, 6, "pending", False,
    ),
    (
        "Competitor comparison — why choose you?",
        "Wendy Clark", "wclark@outlook.com",
        "We are evaluating your platform against Competitor X. Could you share a comparison document highlighting your key differentiators and unique features?",
        "neutral", 0.25, "neutral",
        "sales", "medium", 2,
        "Prospect comparing against Competitor X. Needs differentiator document.",
        "Hi Wendy! Great question. Our key differentiators: real-time AI sentiment analysis, automated routing, 99.9% uptime SLA, and SOC2 certification. I'll send a full comparison doc within the hour.",
        True, 14, "replied", False,
    ),
    (
        "Need to cancel subscription",
        "Xander Moore", "xmoore@gmail.com",
        "We have decided to go in a different direction and need to cancel our subscription effective end of month. Please advise how to proceed and confirm data deletion.",
        "neutral", -0.20, "neutral",
        "general", "medium", 2,
        "Cancellation request. Wants data deletion confirmation.",
        "Hi Xander, we're sorry to see you go. To cancel: Account → Billing → Cancel Plan. Your data is retained for 30 days then permanently deleted per GDPR. If budget is the concern, we have a Lite plan at $9/month.",
        True, 22, "replied", False,
    ),
    (
        "Bulk import of historical emails",
        "Yasmine Ali", "yasmine.a@gmail.com",
        "Is there a way to import our 3 years of historical emails from Gmail into your platform for analysis? We have about 50,000 emails.",
        "positive", 0.40, "neutral",
        "support", "medium", 2,
        "Needs bulk import of 50k historical Gmail emails for analysis.",
        "Hi Yasmine! Yes — use our Gmail Import tool under Settings → Integrations → Gmail → Import History. It handles up to 100k emails. Set the date range and we'll process in the background. Usually takes 2-4 hours.",
        False, 28, "pending", False,
    ),
    (
        "Duplicate emails appearing in inbox",
        "Zara Thompson", "zara.t@outlook.com",
        "Emails are appearing twice in my inbox. Every new email shows up two times. This started after I connected my Outlook integration yesterday.",
        "negative", -0.52, "frustration",
        "support", "high", 3,
        "Duplicate emails after Outlook integration connection.",
        "Hi Zara, this is caused by having both IMAP and OAuth sync enabled simultaneously. Go to Integrations → Outlook → Advanced → disable IMAP sync. Duplicates will be cleaned up automatically.",
        True, 16, "replied", False,
    ),
    # 5 older emails with no replies (pending / ignored)
    (
        "Spam filter too aggressive",
        "Aaron Mitchell", "aaron.m@gmail.com",
        "Your spam filter is blocking legitimate emails from our partners. We have whitelisted the domains but the problem persists.",
        "negative", -0.48, "frustration",
        "support", "medium", 2,
        "Overly aggressive spam filter blocking whitelisted partner domains.",
        None, False, 72, "pending", True,
    ),
    (
        "Question about API authentication methods",
        "Beth Sanders", "beth.s@icloud.com",
        "What authentication methods does your API support? We are building an integration and need to know if you support OAuth 2.0 and API keys.",
        "neutral", 0.15, "neutral",
        "general", "low", 1,
        "Developer question about API auth support (OAuth 2.0 / API keys).",
        None, False, 50, "pending", False,
    ),
    (
        "Wrong plan shown in dashboard",
        "Chris Lang", "clang@yahoo.com",
        "My dashboard says I'm on the Starter plan but I upgraded to Pro 3 days ago and was charged. Please fix this.",
        "negative", -0.61, "concern",
        "complaint", "high", 3,
        "Dashboard showing wrong plan after Pro upgrade 3 days ago. Charge confirmed.",
        None, False, 80, "ignored", False,
    ),
    (
        "Setup wizard keeps timing out",
        "Dana Kim", "dana.k@gmail.com",
        "Every time I try to complete the setup wizard it times out on step 3 of 5. I've tried three different browsers. Very frustrating.",
        "negative", -0.57, "frustration",
        "support", "medium", 2,
        "Setup wizard timeout on step 3 across multiple browsers.",
        None, False, 96, "pending", True,
    ),
    (
        "Very impressed — signed up after the webinar",
        "Ethan Park", "epark@protonmail.com",
        "Just signed up after attending your Tuesday webinar. The demo was excellent and the AI features are exactly what we've been looking for. Excited to get started!",
        "positive", 0.89, "excitement",
        "general", "low", 1,
        "New sign-up post-webinar. Very enthusiastic about AI features.",
        None, False, 44, "pending", False,
    ),
]

email_objs   = []
analysis_objs = []

for i, row in enumerate(EMAILS):
    (subject, sender_name, sender_email, body, sentiment, score, emotion,
     category, priority, p_score, summary, reply_text,
     is_read, hours_ago, reply_status, sla_breach) = row

    msg_id = f"fullseed-{i+1:03d}@mailai.local"
    email_obj = exists(Email, message_id=msg_id)

    if not email_obj:
        integ = integration_objs[i % len(integration_objs)]
        email_obj = Email(
            message_id=msg_id,
            integration_id=integ.id,
            subject=subject,
            sender_name=sender_name,
            sender_email=sender_email,
            recipient_email=integ.email_address,
            body_plain=body,
            body_clean=body,
            received_at=ago(hours=hours_ago),
            processed_at=ago(hours=max(0, hours_ago - 0.5)),
            is_read=is_read,
            is_archived=False,
            thread_id=f"thread-seed-{i+1:03d}",
        )
        db.add(email_obj)
        db.flush()

    email_objs.append(email_obj)

    # ── Analysis ──────────────────────────────────────────────
    an = exists(EmailAnalysis, email_id=email_obj.id)
    if not an:
        routing_map = {
            "complaint": "complaints-team",
            "support":   "technical-support",
            "sales":     "sales-team",
            "refund":    "billing-team",
            "invoice":   "billing-team",
            "feedback":  "product-team",
            "general":   "general-support",
        }
        an = EmailAnalysis(
            email_id=email_obj.id,
            sentiment=sentiment,
            sentiment_score=score,
            primary_emotion=emotion,
            emotions_json=[{"emotion": emotion, "score": abs(score)},
                           {"emotion": "neutral", "score": round(1 - abs(score), 2)}],
            category=category,
            category_confidence=round(0.80 + random.uniform(0, 0.18), 3),
            priority=priority,
            priority_score=p_score,
            ai_summary=summary,
            suggested_reply=reply_text or "Thank you for your message. Our team will review and respond shortly.",
            routed_to=routing_map.get(category, "general-support"),
            routing_reason="Routed by AI based on category and priority",
            model_version="gpt-4o-mini",
            processing_time_ms=90 + i * 8 + random.randint(0, 40),
        )
        db.add(an)
        db.flush()

    analysis_objs.append(an)

    # ── Notification ──────────────────────────────────────────
    if not exists(Notification, email_id=email_obj.id, type="new_email"):
        db.add(Notification(
            email_id=email_obj.id,
            type="new_email",
            title=f"📧 New email: {subject[:60]}",
            message=f"From: {sender_email} | {sentiment.capitalize()} | {category.capitalize()}",
            is_read=is_read,
            created_at=ago(hours=hours_ago),
        ))
    if priority in ("critical", "high") and not exists(Notification, email_id=email_obj.id, type="urgent"):
        db.add(Notification(
            email_id=email_obj.id,
            type="urgent",
            title=f"⚠ {priority.upper()}: {subject[:55]}",
            message=f"From: {sender_email} | Sentiment: {sentiment}",
            is_read=False,
            created_at=ago(hours=hours_ago),
        ))

    # ── Reply ─────────────────────────────────────────────────
    if reply_text and reply_status == "replied":
        existing_reply = db.query(EmailReply).filter_by(email_id=email_obj.id).first()
        if not existing_reply:
            sent_at = ago(hours=max(0, hours_ago - random.uniform(0.5, 4)))
            reply_obj = EmailReply(
                email_id=email_obj.id,
                subject=f"Re: {subject}",
                body=reply_text,
                attachments_json=[],
                is_draft=False,
                sent_at=sent_at,
                created_at=sent_at,
            )
            db.add(reply_obj)
            db.flush()

            # Response tracker
            if not exists(EmailResponseTracker, email_id=email_obj.id):
                received = email_obj.received_at
                response_mins = int((sent_at - received).total_seconds() / 60)
                sla_mins = {"critical": 60, "high": 240, "medium": 1440, "low": 4320}
                threshold = sla_mins.get(priority, 1440)
                db.add(EmailResponseTracker(
                    email_id=email_obj.id,
                    reply_id=reply_obj.id,
                    responded_by_user_id=user_objs["alice"].id if i % 2 == 0 else user_objs["bob"].id,
                    status="replied",
                    first_response_minutes=max(0, response_mins),
                    sla_breach=sla_breach or (response_mins > threshold),
                    notes=None,
                ))

    elif reply_status in ("pending", "escalated", "ignored"):
        if not exists(EmailResponseTracker, email_id=email_obj.id):
            db.add(EmailResponseTracker(
                email_id=email_obj.id,
                reply_id=None,
                responded_by_user_id=None,
                status=reply_status,
                first_response_minutes=None,
                sla_breach=sla_breach,
                escalated_to="senior-support" if reply_status == "escalated" else None,
                notes="Escalated due to critical impact" if reply_status == "escalated" else None,
            ))

db.commit()
p(f"{len(EMAILS)} emails created with analyses, notifications, replies, and tracker entries")


# ══════════════════════════════════════════════════════════════
# SUMMARY
# ══════════════════════════════════════════════════════════════
print()
print("═" * 58)
print("  SEED COMPLETE — Summary")
print("═" * 58)

from sqlalchemy import func as sqlfunc

counts = {
    "Users":              db.query(sqlfunc.count(User.id)).scalar(),
    "User Sessions":      db.query(sqlfunc.count(UserSession.id)).scalar(),
    "Audit Logs":         db.query(sqlfunc.count(AuditLog.id)).scalar(),
    "API Request Logs":   db.query(sqlfunc.count(ApiRequestLog.id)).scalar(),
    "Email Integrations": db.query(sqlfunc.count(EmailIntegration.id)).scalar(),
    "Emails":             db.query(sqlfunc.count(Email.id)).scalar(),
    "Email Analyses":     db.query(sqlfunc.count(EmailAnalysis.id)).scalar(),
    "Notifications":      db.query(sqlfunc.count(Notification.id)).scalar(),
    "Email Replies":      db.query(sqlfunc.count(EmailReply.id)).scalar(),
    "Response Tracker":   db.query(sqlfunc.count(EmailResponseTracker.id)).scalar(),
    "Allowed Domains":    db.query(sqlfunc.count(AllowedDomain.id)).scalar(),
}

for label, count in counts.items():
    print(f"  {label:<22} {count:>5} rows")

print()
print("  CREDENTIALS")
print("  ┌──────────────┬──────────────┬──────────────┐")
print("  │ username     │ password     │ role         │")
print("  ├──────────────┼──────────────┼──────────────┤")
print("  │ admin        │ admin123     │ admin        │")
print("  │ manager      │ manager123   │ admin        │")
print("  │ alice        │ alice123     │ employee     │")
print("  │ bob          │ bob123       │ employee     │")
print("  │ carol        │ carol123     │ employee     │")
print("  │ david        │ david123     │ employee     │")
print("  │ employee     │ emp123       │ employee     │")
print("  └──────────────┴──────────────┴──────────────┘")
print("═" * 58)

db.close()
