"""
Auto-routing service.
Determines which team/department should handle an email.
"""
from dataclasses import dataclass


# Routing rules: category + optional sentiment overrides
_ROUTING_RULES: list[tuple[dict, str, str]] = [
    # (conditions, team, reason)
    ({"category": "complaint",    "priority": "critical"}, "support_escalated", "Critical complaint — escalated support"),
    ({"category": "complaint"},                            "support",           "Complaint routed to support team"),
    ({"category": "refund"},                               "finance",           "Refund request routed to finance team"),
    ({"category": "invoice"},                              "finance",           "Invoice query routed to finance team"),
    ({"category": "support"},                              "support",           "Support request routed to support team"),
    ({"category": "sales"},                                "sales",             "Sales inquiry routed to sales team"),
    ({"category": "feedback"},                             "product",           "Feedback routed to product team"),
    ({"category": "general",      "sentiment": "negative"}, "support",         "Negative email routed to support for review"),
]


@dataclass
class RoutingResult:
    team: str
    reason: str


def route_email(
    category: str,
    sentiment: str,
    priority: str,
) -> RoutingResult:
    """
    Determine the destination team for an email.
    Evaluates routing rules in order; first match wins.
    """
    ctx = {"category": category, "sentiment": sentiment, "priority": priority}

    for conditions, team, reason in _ROUTING_RULES:
        if all(ctx.get(k) == v for k, v in conditions.items()):
            return RoutingResult(team=team, reason=reason)

    return RoutingResult(team="support", reason="Default routing to support team")
