"""Categorization engine: rules + learning.

Order of resolution for a transaction:
  1. User/DB rules (lower `priority` value wins; learned rules default to 10).
  2. Built-in starter ruleset (~300 patterns, see _STARTER for its priority order).
  3. Fallback to "Uncategorized".

A "rule" is a case-insensitive substring match against the transaction
description. When the user re-categorizes something in the UI, we persist a
rule so the same merchant is automatic next time (the "learning" part).
"""
from __future__ import annotations
from .db import db

# Built-in starter rules: an ORDERED list of (category, direction, patterns).
# Patterns are matched as UPPERCASE substrings of the description; list order
# is priority — the first matching pattern wins. direction: 'any' | 'in'
# (money in, amount < 0) | 'out' (spend, amount > 0).
#
# Ordering is deliberate:
#   1. Card-payment descriptors FIRST, so a debit charge that pays off a credit
#      card is always Transfer/Payment and never double-counted as a Bill.
#   2. Income next, direction-gated so "REFUND"/"DEPOSIT" never claim spending.
#   3. Bills before the merchant groups (loan servicers beat generic keywords).
#   4. Food before Transport ("UBER EATS" vs "UBER"), Transport before Grocery
#      ("COSTCO GAS" vs "COSTCO"), Health before Travel ("DELTA DENTAL" vs
#      "DELTA").
#   5. GENERIC transfer indicators ("AUTOPAY", "ONLINE PAYMENT", "PYMT") dead
#      LAST, so "ONLINE PAYMENT TO PORTLAND GENERAL" still lands in Bills.
_STARTER: list[tuple[str, str, list[str]]] = [
    # --- 1. Credit-card payments (both sides of the transfer) ---------------
    ("Transfer/Payment", "any", [
        # Chase credit statement (money in) and Chase checking (money out).
        "PAYMENT THANK YOU", "PAYMENT-THANK YOU", "PAYMENT - THANK YOU",
        "CHASE CREDIT CRD", "PAYMENT TO CHASE CARD", "CHASE CARD ENDING",
        # BofA credit statement and the matching checking-side descriptors.
        "BANK OF AMERICA CREDIT CARD", "BA ELECTRONIC PAYMENT",
        "BANK OF AMERICA PAYMENT", "BOFA CREDIT CARD",
        # Other issuers, in case a payment leaves the Chase debit account.
        "CRCARDPMT", "CREDIT CARD PMT", "CREDIT CRD PMT", "CREDIT CARD PAYMENT",
        "APPLECARD GSBANK", "DISCOVER E-PAYMENT", "DISCOVER PAYMENTS",
        "CITI AUTOPAY", "CITI CARD ONLINE", "AMEX EPAYMENT",
        "BARCLAYCARD", "SYNCHRONY BANK", "CARDMEMBER SERV",
    ]),
    # --- 2. Income (only ever money in) --------------------------------------
    ("Income", "in", [
        "PAYROLL", "DIRECT DEP", "DIRECTDEP", "DIR DEP", "DEPOSIT",
        "INTEREST PAID", "DIVIDEND", "IRS TREAS", "US TREASURY", "SSA TREAS",
        "REFUND", "REVERSAL", "CASHBACK", "CASH BACK",
        "DEEL INC", "DEEL ", "GUSTO", "PAYCHEX", "ADP PAY", "TRINET", "RIPPLING",
        "OR REVENUE DEPT", "ORSTTAXRFD", "TAX REF", "UNEMPLOYMENT",
        # Money in via P2P apps counts as income (e.g. reimbursements for
        # DoorDash orders / the Unitus car payment). Outgoing P2P is handled
        # elsewhere: Venmo/Cash App out -> Fun (learned rules), Apple Cash
        # out -> Transfer/Payment (generic tail).
        "VENMO", "CASH APP", "APPLE CASH",
    ]),
    # --- 3. Bills: mortgage/rent, loans, car, utilities, insurance, phone ----
    ("Bills", "any", [
        # Mortgage & rent ("MTG PYMT" covers e.g. "FREEDOM MTG PYMTS")
        "MORTGAGE", "ROCKET MTG", "FREEDOM MTG", "MR COOPER", "MR. COOPER",
        "NATIONSTAR", "PENNYMAC", "NEWREZ", "SHELLPOINT", "LOANDEPOT",
        "CALIBER HOME", "HOME LOAN", "MTG PMT", "MTG PYMT", "RENT PMT",
        "RENT PAYMENT", "PROPERTY MGMT", "PROPERTY MANAGEMENT", "HOA DUES",
        "HOA ",
        # Student loans
        "STUDENT LN", "STUDENT LOAN", "DEPT EDUCATION", "NELNET", "MOHELA",
        "AIDVANTAGE", "NAVIENT", "GREAT LAKES", "EDFINANCIAL", "SALLIE MAE",
        "FIRSTMARK", "EARNEST",
        # Car payments
        "CARMAX", "CARVANA", "BRIDGECREST", "TOYOTA FINANCIAL", "HONDA FIN",
        "GM FINANCIAL", "FORD CREDIT", "NISSAN MOTOR AC", "HYUNDAI MOTOR FIN",
        "KIA MOTORS FIN", "ALLY FIN", "ALLY AUTO", "CAPITAL ONE AUTO",
        "CHASE AUTO", "WESTLAKE FIN", "SANTANDER CONSUMER", "VW CREDIT",
        "BMW FINANCIAL", "TESLA FIN", "AUTO LOAN", "CAR LOAN",
        # Utilities: power, gas, water, trash
        "PG&E", "PGANDE", "PORTLAND GENERAL", "PACIFIC POWER", "PACIFICORP",
        "EDISON", "DUKE ENERGY", "DOMINION ENERGY", "PUGET SOUND ENERGY",
        "AVISTA", "SOUTHWEST GAS", "SOCALGAS", "SDG&E", "NATIONAL GRID",
        "NW NATURAL", "NORTHWEST NATURAL", "NORTHWEST NATURA",
        "ELECTRIC", "ENERGY BILL", "GAS COMPANY", "WATER DISTRICT",
        # "CITY OF GRESHAM", not bare "GRESHAM": every local merchant's
        # descriptor ends in "GRESHAM OR" and must not become a Bill.
        "WATER BUREAU", "WATER/SEWER", "SEWER", "UTILITY", "CITY OF GRESHAM",
        "WASTE MANAGEMENT", "WASTE MGMT", "WM EZPAY", "WM.COM",
        "REPUBLIC SERVICES", "RECOLOGY", "WASTE CONNECTIONS", "GARBAGE",
        "DISPOSAL",
        # Home services, collections, tax prep
        "APTIVE", "TERMINIX", "ORKIN", "IC SYSTEM", "JACKSON HEWITT",
        "H&R BLOCK", "TURBOTAX",
        # Internet / TV / phone
        "COMCAST", "XFINITY", "SPECTRUM", "CENTURYLINK", "LUMEN", "ZIPLY",
        "FRONTIER COMM", "COX COMM", "DISH NETWORK", "DIRECTV",
        "AT&T", "VERIZON", "T-MOBILE", "TMOBILE", "MINT MOBILE", "GOOGLE FI",
        "VISIBLE", "CRICKET WIRELESS", "BOOST MOBILE", "US CELLULAR",
        "CONSUMER CELLULAR",
        # Insurance
        "INSURANCE", "GEICO", "STATE FARM", "PROGRESSIVE", "ALLSTATE",
        "FARMERS INS", "LIBERTY MUTUAL", "USAA P&C", "NATIONWIDE", "PEMCO",
        "UNITEDHEALTH", "AMERICAN STRATEG",   # American Strategic Insurance
        # Household
        "LAUNDRY", "LAUNDROMAT",
    ]),
    # --- 4. Bank/card fees ----------------------------------------------------
    ("Fees", "any", [
        "PURCHASE INTEREST CHARGE", "INTEREST CHARGED", "INTEREST CHARGE",
        "FINANCE CHARGE", "FOREIGN TRANSACTION FEE", "LATE FEE", "ANNUAL FEE",
        "OVERDRAFT", "NSF FEE", "SERVICE FEE", "MAINTENANCE FEE", "WIRE FEE",
        "ATM FEE", "MEMBERSHIP FEE", "APPRAISALFEE", "APPRAISAL FEE",
        "COUNTER CHECK", "OFFICIAL CHECK", "RETURNED ITEM", "CASH ADVANCE",
    ]),
    # --- 5. Merchant groups ---------------------------------------------------
    ("Subscriptions", "any", [
        "NETFLIX", "SPOTIFY", "HULU", "DISNEY PLUS", "DISNEY+", "HBO", "MAX.COM",
        "YOUTUBE PREMIUM", "YOUTUBE TV", "GOOGLE YOUTUBE", "PRIME VIDEO",
        "AMAZON PRIME", "APPLE.COM/BILL", "GOOGLE STORAGE", "GOOGLE ONE",
        "ICLOUD", "DROPBOX", "ADOBE", "MICROSOFT 365", "AUDIBLE", "PATREON",
        "SUBSTACK", "NYTIMES", "MEDIUM", "PEACOCK", "PARAMOUNT", "CRUNCHYROLL",
        "SIRIUSXM", "PANDORA", "TWITCH", "CHATGPT", "OPENAI", "ANTHROPIC",
        "CLAUDE.AI", "GITHUB", "JETBRAINS", "MIDJOURNEY", "NORDVPN",
        "EXPRESSVPN", "1PASSWORD", "LASTPASS", "CANVA", "NOTION", "FIGMA",
        "TWILIO",
        # Microsoft card charges here are Game Pass / 365 / storage renewals
        # (descriptors appear both as "MICROSOFT*..." and bare "MICROSOFT").
        "MICROSOFT", "GAME PASS",
    ]),
    ("Food", "any", [
        "MCDONALD", "STARBUCKS", "CHIPOTLE", "DOORDASH", "UBER EATS", "UBEREATS",
        "GRUBHUB", "POSTMATES", "PANERA", "CHICK-FIL-A", "CHICKFILA", "TACO BELL",
        "WENDY", "BURGER KING", "DUNKIN", "SUBWAY", "PIZZA", "DOMINO", "SUSHI",
        "PANDA EXPRESS", "FIVE GUYS", "IN-N-OUT", "SHAKE SHACK", "QDOBA",
        "JIMMY JOHN", "JERSEY MIKE", "POPEYES", "KFC ", "SONIC DRIVE", "ARBY",
        "CARL'S JR", "JACK IN THE BOX", "LITTLE CAESAR", "PAPA JOHN",
        "PAPA MURPHY", "DUTCH BROS", "PEET'S", "BOSTON MARKET", "RED ROBIN",
        "BUFFALO WILD", "CHART HOUSE", "DENNY'S", "DENNYS", "MENCHIE",
        # Gresham / Portland-metro locals
        "BIG TOWN HERO", "BIGTOWNHERO", "HOPS N DROPS", "DRAGON PALACE",
        "KKOKI",
        # "TST*" = Toast POS and "DD *" = DoorDash/Caviar — restaurants only.
        # "RESTAU" also catches descriptors truncated before "RESTAURANT"
        # finishes; "TACO " (not bare "TACO") avoids matching TACOMA.
        "TST*", "DD *", "TAQUERIA", "TACO ", "TACOS", "BANH MI", "BBQ",
        "BUFFET", "CATERING", "RAMEN", "PHO ", "BISTRO", "EATERY", "FOOD CART",
        "FOOD TRUCK", "RESTAU", "CAFE", "COFFEE", "GRILL", "KITCHEN",
        "BAR & GRILL", "DELI", "BAKERY", "DINER",
        "SHARETEA", "BOBA", "BUBBLE TEA", "BRAGANZA", "FROZEN YOGURT",
        "DAIRY QUEEN",
    ]),
    ("Transport", "any", [
        "UBER", "LYFT", "SHELL", "CHEVRON", "EXXONMOBIL", "EXXON", "ARCO",
        "VALERO", "TEXACO", "CIRCLE K", "SPEEDWAY", "COSTCO GAS", "FUEL",
        "CHARGEPOINT", "EVGO", "ELECTRIFY AMERICA", "TESLA SUPERCHARG",
        "PARKING", "PARKING KITTY", "PAYBYPHONE", "PARKMOBILE", "TOLL",
        "GOODTOGO", "FASTRAK", "TRI-MET", "TRIMET", "TRANSIT", "MTA*",
        "CALTRAIN", "AMTRAK", "BIKETOWN", "AUTOZONE", "O'REILLY AUTO",
        "CAR WASH", "JIFFY LUBE", "LES SCHWAB", "DISCOUNT TIRE", "DMV", "ODOT",
        "SPACE AGE", "LEARN TO DRIVE",
    ]),
    ("Grocery", "any", [
        "WHOLE FOODS", "TRADER JOE", "SAFEWAY", "KROGER", "ALBERTSONS", "PUBLIX",
        "WEGMANS", "ALDI", "LIDL", "SPROUTS", "H-E-B", "HEB ", "RALPHS", "VONS",
        "FOOD LION", "GIANT", "STOP & SHOP", "COSTCO", "SAM'S CLUB", "SAMS CLUB",
        "WINCO", "WALMART", "WAL-MART", "WM SUPERCENTER", "FRED MEYER",
        "FRED-MEYER", "FREDMEYER", "MEIJER", "H MART", "HMART",
        "INTERNATIONAL MARK", "ORIENTAL FOOD", "MINUTE MART",
        "NEW SEASONS", "QFC", "GROCERY OUTLET", "NATURAL GROCERS",
        "MARKET OF CHOICE", "ZUPAN", "HARRIS TEETER", "HY-VEE", "HANNAFORD",
        "SHOPRITE", "WINN-DIXIE", "KING SOOPERS", "SMITH'S", "FOOD 4 LESS",
        "STATER BROS", "PIGGLY", "INSTACART",
        "GROCERY", "SUPERMARKET", "MARKET",
    ]),
    ("Health", "any", [
        "CVS", "WALGREENS", "RITE AID", "PHARMACY", "DENTAL", "DENTIST",
        "ORTHODON", "MEDICAL", "CLINIC", "HOSPITAL", "DOCTOR", "URGENT CARE",
        "KAISER", "OHSU", "LEGACY HEALTH", "ZOOMCARE", "LABCORP",
        "QUEST DIAGNOSTICS", "CHIROPRAC", "THERAPY", "COUNSELING", "VISION",
        "OPTOMETRY", "FITNESS", "GYM", "PLANET FIT", "EQUINOX", "24 HOUR FIT",
        "CROSSFIT", "YMCA", "ORANGETHEORY",
    ]),
    ("Shopping", "any", [
        "AMAZON", "AMZN", "TARGET", "BEST BUY", "HOME DEPOT", "LOWE'S",
        "LOWES", "IKEA", "WAYFAIR", "ETSY", "EBAY", "TEMU", "SHEIN",
        "ALIEXPRESS", "MACY", "NORDSTROM", "NIKE", "ADIDAS", "OLD NAVY", "GAP",
        "H&M", "ZARA", "UNIQLO", "LULULEMON", "SEPHORA", "ULTA", "APPLE STORE",
        "DICK'S SPORTING", "REI ", "REI.COM", "PETSMART", "PETCO", "CHEWY",
        "MICHAELS", "JOANN", "HOBBY LOBBY", "BARNES & NOBLE", "POWELL",
        "MENS WEARHOUSE", "MEN'S WEARHOUSE", "VANS ", "POSHMARK", " LUSH ",
        "USPS", "KOHL'S", "KOHLS", "AMERICAN EAGLE", "CRAFT WAREHOUSE",
        "MINISO", "SALLY BEAUTY",
        "DOLLAR TREE", "DOLLARTREE", "DOLLAR GENERAL", "FIVE BELOW",
        "A TO Z PETS", "ROSS DRESS", "TJ MAXX",
        "TJMAXX", "MARSHALLS", "HOMEGOODS", "BED BATH", "WILLIAMS-SONOMA",
        "CRATE & BARREL", "GOODWILL", "HARBOR FREIGHT", "ACE HARDWARE",
        "ACE HDWE", "TRUE VALUE",
    ]),
    ("Fun", "any", [
        "STEAM GAMES", "STEAMGAMES", "PLAYSTATION", "XBOX", "NINTENDO",
        "EPIC GAMES", "RIOT GAMES", "BLIZZARD", "AMC ", "CINEMARK", "REGAL",
        "FANDANGO", "CINEMA", "THEATRE", "THEATER", "TICKETMASTER", "STUBHUB",
        "EVENTBRITE", "MUSEUM", "AQUARIUM", "GOLF", "TOPGOLF", "BOWLING",
        "ARCADE", "DAVE & BUSTER", "LIQUOR", "BREWERY", "BREWING", "WINERY",
        "DISTILLERY", "TAPROOM", "TAVERN", "PUB ", "CASINO",
        "MT HOOD MEADOWS", "SKIBOWL", "TIMBERLINE", "HEADOUT", "OREGON ZOO",
        "AXS.COM", "SMOKE SHOP", "VAPE", "TOBACC", "PUFF PUFF", "FUDGIE WUDGIE",
        # "SQ *" = Square POS: catch-all for one-off event/fair vendors. Sits
        # in Fun (late priority) so a Square coffee shop still matches Food
        # first via CAFE/COFFEE/TACO-style patterns above.
        "SQ *",
    ]),
    ("Travel", "any", [
        "DELTA", "UNITED AIR", "AMERICAN AIR", "SOUTHWEST", "JETBLUE",
        "ALASKA AIR", "SPIRIT AIR", "FRONTIER AIR", "ALLEGIANT", "HAWAIIAN AIR",
        "AIRBNB", "VRBO", "MARRIOTT", "HILTON", "HYATT", "EXPEDIA",
        "BOOKING.COM", "PRICELINE", "HOTELS.COM", "HOTEL", "MOTEL", "RESORT",
        "AIRLINE", "RENTAL CAR", "HERTZ", "ENTERPRISE RENT", "TURO", "CRUISE",
        "GREYHOUND", "FLIXBUS", "POINT.ME",
    ]),
    # --- 6. Generic transfer indicators — LAST so specific billers win -------
    ("Transfer/Payment", "any", [
        "ONLINE PAYMENT", "AUTOPAY", "AUTO PAY", "AUTOMATIC PAYMENT", "PYMT",
        "EPAY", "E-PAYMENT", "TRANSFER TO", "TRANSFER FROM", "ONLINE TRANSFER",
        "ZELLE", "WIRE TRANSFER", "ACH DEBIT", "ACH CREDIT", "ACH PMT",
        "ACH WITHDRAWAL", "ACH TRANSFER", "WITHDRAWAL", "ATM", "CARD PAYMENT",
        "BILL PAYMENT", "ONLINE/MOBILE", "APPLE CASH", "TRNWISE", "WISE INC",
    ]),
]

# Flattened to (pattern, category, direction). Earlier entries win on ties.
STARTER_RULES: list[tuple[str, str, str]] = [
    (pat.upper(), cat, direction)
    for cat, direction, pats in _STARTER
    for pat in pats
]


def get_rules() -> list[tuple[str, str, int, str]]:
    """Learned rules as (PATTERN, category, priority, direction), priority-sorted."""
    with db() as conn:
        rows = conn.execute(
            "SELECT pattern, category, priority, direction FROM rules "
            "ORDER BY priority ASC, id ASC"
        ).fetchall()
    return [(r["pattern"].upper(), r["category"], r["priority"], r["direction"]) for r in rows]


def list_rules() -> list[dict]:
    """Full rule rows for the management UI/API."""
    with db() as conn:
        rows = conn.execute(
            "SELECT id, pattern, category, priority, direction, created_at "
            "FROM rules ORDER BY priority ASC, id ASC"
        ).fetchall()
    return [dict(r) for r in rows]


def delete_rule(rule_id: int) -> bool:
    """Delete a learned rule. Returns False if the id doesn't exist."""
    with db() as conn:
        cur = conn.execute("DELETE FROM rules WHERE id = ?", (rule_id,))
    return cur.rowcount > 0


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
    rules = get_rules() if db_rules is None else db_rules

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
    """Recompute categories for every stored transaction. Returns count changed.

    Transactions the user pinned by hand (manually_set = 1) are left alone.
    """
    rules = get_rules()
    changed = 0
    with db() as conn:
        rows = conn.execute(
            "SELECT id, description, amount, raw_category, category "
            "FROM transactions WHERE manually_set = 0"
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
