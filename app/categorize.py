"""Categorization engine: rules + learning.

Order of resolution for a transaction:
  1. User/DB rules (lower `priority` value wins; learned rules default to 10).
  2. Built-in starter ruleset (~80 common merchants).
  3. Fallback to "Uncategorized".

A "rule" is a case-insensitive substring match against the transaction
description. When the user re-categorizes something in the UI, we persist a
rule so the same merchant is automatic next time (the "learning" part).
"""
from __future__ import annotations
from .db import db

# Built-in starter rules. Grouped by category for readability, flattened below.
# Patterns are matched as UPPERCASE substrings of the description.
_STARTER: dict[str, list[str]] = {
    "Subscriptions": [
        "NETFLIX", "SPOTIFY", "HULU", "DISNEY PLUS", "DISNEY+", "HBO", "MAX.COM",
        "YOUTUBE PREMIUM", "PRIME VIDEO", "APPLE.COM/BILL", "GOOGLE STORAGE",
        "ICLOUD", "DROPBOX", "ADOBE", "MICROSOFT 365", "AUDIBLE", "PATREON",
        "NYTIMES", "MEDIUM", "PEACOCK", "PARAMOUNT", "CHATGPT", "OPENAI",
        "ANTHROPIC", "CLAUDE.AI", "GITHUB",
    ],
    "Food": [
        "MCDONALD", "STARBUCKS", "CHIPOTLE", "DOORDASH", "UBER EATS", "UBEREATS",
        "GRUBHUB", "POSTMATES", "PANERA", "CHICK-FIL-A", "CHICKFILA", "TACO BELL",
        "WENDY", "BURGER KING", "DUNKIN", "SUBWAY", "PIZZA", "DOMINO", "SUSHI",
        "RESTAURANT", "CAFE", "COFFEE", "GRILL", "KITCHEN", "BAR & GRILL",
        "DELI", "BAKERY", "DINER",
    ],
    "Grocery": [
        "WHOLE FOODS", "TRADER JOE", "SAFEWAY", "KROGER", "ALBERTSONS", "PUBLIX",
        "WEGMANS", "ALDI", "SPROUTS", "H-E-B", "HEB ", "RALPHS", "VONS",
        "FOOD LION", "GIANT", "STOP & SHOP", "COSTCO", "SAM'S CLUB", "SAMS CLUB",
        "WINCO", "WALMART", "WAL-MART", "FRED MEYER", "FREDMEYER",
        "GROCERY", "SUPERMARKET", "MARKET",
    ],
    "Transport": [
        "UBER", "LYFT", "SHELL", "CHEVRON", "EXXONMOBIL", "EXXON", "ARCO",
        "VALERO", "TEXACO", "FUEL", "PARKING", "TOLL", "TRI-MET", "TRIMET",
        "TRANSIT", "CALTRAIN", "AUTOZONE", "CAR WASH", "JIFFY LUBE",
    ],
    "Bills": [
        "AT&T", "VERIZON", "T-MOBILE", "TMOBILE", "COMCAST", "XFINITY", "SPECTRUM",
        "PG&E", "PGANDE", "EDISON", "ELECTRIC", "WATER DISTRICT", "GAS COMPANY",
        "INSURANCE", "GEICO", "STATE FARM", "PROGRESSIVE", "ALLSTATE", "RENT",
        "MORTGAGE", "UTILITY", "WASTE MANAGEMENT",
        "GRESHAM", "DEPT EDUCATION STUDENT LN", "CARMAX",
        "NW NATURAL", "NORTHWEST NATURAL", "NORTHWEST NATURA",
    ],
    "Fees": [
        "PURCHASE INTEREST CHARGE", "INTEREST CHARGED", "INTEREST CHARGE",
        "FINANCE CHARGE", "FOREIGN TRANSACTION FEE", "LATE FEE", "ANNUAL FEE",
        "OVERDRAFT", "NSF FEE", "SERVICE FEE", "RETURNED ITEM",
    ],
    "Health": [
        "CVS", "WALGREENS", "RITE AID", "PHARMACY", "DENTAL", "DENTIST",
        "MEDICAL", "CLINIC", "HOSPITAL", "DOCTOR", "VISION", "OPTOMETRY",
        "FITNESS", "GYM", "PLANET FIT", "EQUINOX", "24 HOUR FIT",
    ],
    "Shopping": [
        "AMAZON", "AMZN", "TARGET", "BEST BUY", "HOME DEPOT", "LOWE'S",
        "LOWES", "IKEA", "ETSY", "EBAY", "MACY", "NORDSTROM", "NIKE", "ADIDAS",
        "OLD NAVY", "GAP", "H&M", "ZARA", "SEPHORA", "ULTA", "APPLE STORE",
    ],
    "Fun": [
        "STEAM GAMES", "PLAYSTATION", "XBOX", "NINTENDO", "AMC ", "CINEMARK",
        "REGAL", "FANDANGO", "TICKETMASTER", "STUBHUB", "EVENTBRITE", "GOLF",
        "BOWLING", "ARCADE", "LIQUOR", "BREWERY", "TAVERN", "PUB ", "CASINO",
    ],
    "Travel": [
        "DELTA", "UNITED AIR", "AMERICAN AIR", "SOUTHWEST", "JETBLUE", "ALASKA AIR",
        "AIRBNB", "MARRIOTT", "HILTON", "HYATT", "EXPEDIA", "BOOKING.COM",
        "HOTEL", "AIRLINE", "RENTAL CAR", "HERTZ", "ENTERPRISE RENT",
    ],
    "Income": [
        "PAYROLL", "DIRECT DEP", "DIRECTDEP", "DEPOSIT", "INTEREST PAID",
        "DIVIDEND", "IRS TREAS", "REFUND", "DEEL INC", "DEEL ",
        "OR REVENUE DEPT", "ORSTTAXRFD", "TAX REF",
    ],
    "Transfer/Payment": [
        "PAYMENT THANK YOU", "ONLINE PAYMENT", "AUTOPAY", "AUTO PAY", "PYMT",
        "EPAY", "TRANSFER TO", "TRANSFER FROM", "ZELLE", "WIRE TRANSFER",
        "ACH", "WITHDRAWAL", "ATM", "CARD PAYMENT", "BILL PAYMENT",
        "PAYMENT TO CHASE CARD", "CHASE CREDIT CRD", "AUTOMATIC PAYMENT",
        "ONLINE/MOBILE", "BANK OF AMERICA PAYMENT",
    ],
}

# Conditional starter rules that depend on the direction of money flow.
# direction: 'in' = money in (amount < 0), 'out' = spend (amount > 0).
# e.g. a Venmo that ADDS money is income; a Venmo payment out is not.
_CONDITIONAL_STARTER: list[tuple[str, str, str]] = [
    ("VENMO", "Income", "in"),
    ("CASH APP", "Income", "in"),   # money in via Cash App is income; payments out aren't
]

# Flattened to (pattern, category, direction). Earlier entries win on ties.
STARTER_RULES: list[tuple[str, str, str]] = (
    [(pat.upper(), cat, "any") for cat, pats in _STARTER.items() for pat in pats]
    + [(pat.upper(), cat, d) for pat, cat, d in _CONDITIONAL_STARTER]
)


def _db_rules() -> list[tuple[str, str, int, str]]:
    with db() as conn:
        rows = conn.execute(
            "SELECT pattern, category, priority, direction FROM rules "
            "ORDER BY priority ASC, id ASC"
        ).fetchall()
    return [(r["pattern"].upper(), r["category"], r["priority"], r["direction"]) for r in rows]


def _direction_ok(direction: str, amount: float) -> bool:
    if direction == "in":
        return amount < 0      # money in (income/refund/deposit)
    if direction == "out":
        return amount > 0      # money spent
    return True                # 'any'


def categorize(description: str, amount: float = 0.0, raw_category: str = "",
               db_rules: list[tuple[str, str, int, str]] | None = None) -> str:
    """Return the best category for a transaction.

    ``amount`` follows the normalized convention (positive = spend, negative =
    money in) and is used to evaluate direction-conditional rules.
    Pass ``db_rules`` to avoid a DB round-trip per row during bulk imports.
    """
    # Collapse runs of whitespace — bank descriptions pad fields with many
    # spaces, which would otherwise break multi-word patterns.
    text = " ".join((description or "").upper().split())
    rules = _db_rules() if db_rules is None else db_rules

    # 1. User/DB rules (already priority-sorted).
    for pattern, category, _prio, direction in rules:
        if pattern in text and _direction_ok(direction, amount):
            return category

    # 2. Built-in starter rules.
    for pattern, category, direction in STARTER_RULES:
        if pattern in text and _direction_ok(direction, amount):
            return category

    return "Uncategorized"


def add_rule(pattern: str, category: str, priority: int = 10,
             direction: str = "any") -> None:
    """Persist a learned rule. Learned rules outrank starter rules by default."""
    pattern = pattern.strip()
    if not pattern:
        return
    if direction not in ("any", "in", "out"):
        direction = "any"
    with db() as conn:
        conn.execute(
            """INSERT INTO rules(pattern, category, priority, direction)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(pattern) DO UPDATE SET category=excluded.category,
                                                   priority=excluded.priority,
                                                   direction=excluded.direction""",
            (pattern, category, priority, direction),
        )


def reapply_all() -> int:
    """Recompute categories for every stored transaction. Returns count changed."""
    rules = _db_rules()
    changed = 0
    with db() as conn:
        rows = conn.execute(
            "SELECT id, description, amount, raw_category, category FROM transactions"
        ).fetchall()
        for row in rows:
            new_cat = categorize(row["description"], row["amount"],
                                 row["raw_category"] or "", rules)
            if new_cat != row["category"]:
                conn.execute(
                    "UPDATE transactions SET category=? WHERE id=?",
                    (new_cat, row["id"]),
                )
                changed += 1
    return changed
