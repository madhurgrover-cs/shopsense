"""Fill the database with realistic, reproducible demo data.

Run from the project root:   venv\\Scripts\\python -m scripts.seed

What it creates (see CLAUDE.md "Seed data"):
  2 admins, 50 customers (+ addresses), 8 categories, 200 products (+ stock),
  5 coupons, 500 orders over the last 90 days (+ items, payments, status history),
  300 reviews (sentiment scores are filled afterwards by scripts.backfill_sentiment).

Design notes:
- Re-runnable: every table is TRUNCATEd first, and everything runs in ONE transaction,
  so a failure halfway leaves the database exactly as it was.
- Reproducible: Faker and random are seeded with 42. Dates are relative to "now", so the
  data always covers the last 90 days whenever you run it.
- Order status history is NOT inserted by this script. Orders are inserted as 'placed' and
  then UPDATEd to shipped / delivered / cancelled, so the trg_order_status trigger writes
  the history rows itself. The trigger stamps updates with now() (the time the script
  runs), so afterwards we move those timestamps back to realistic past times.
- Rows are inserted in bulk (one INSERT per table, not one per row), because every round
  trip to Neon over the internet costs time.
"""

import random
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

import bcrypt
from faker import Faker
from sqlalchemy import insert, text
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import (
    Address, Base, Category, Coupon, Inventory, Order, OrderItem, Payment, Product,
    Review, User,
)
from scripts.seed_catalog import BUNDLES, CATALOG, CITIES, REVIEW_TEXT

SEED = 42
N_ADMINS = 2
N_CUSTOMERS = 50
N_ORDERS = 500
N_REVIEWS = 300
DAYS_OF_HISTORY = 90
PASSWORD = "password123"
IST = ZoneInfo("Asia/Kolkata")

fake = Faker("en_IN")
rng = random.Random(SEED)  # our own generator, so other libraries can't disturb the sequence
NOW = datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def inr_price(low: int, high: int) -> Decimal:
    """Random price that ends in 9 (e.g. 1,299 or 349), as Indian stores usually price."""
    value = rng.randint(low, high)
    step = 100 if value >= 1000 else 10
    value = max(step, round(value / step) * step) - 1
    return Decimal(value)


def money(value: Decimal) -> Decimal:
    """Round to paise (2 decimal places)."""
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def bulk_insert(session: Session, model, rows: list[dict], returning_id: bool = False):
    """Insert many rows in one statement. Optionally return the new ids in input order."""
    if not rows:
        return []
    stmt = insert(model)
    if returning_id:
        # sort_by_parameter_order guarantees ids come back in the same order as `rows`.
        stmt = stmt.returning(model.id, sort_by_parameter_order=True)
        return list(session.scalars(stmt, rows))
    session.execute(stmt, rows)
    return []


# ---------------------------------------------------------------------------
# Seeding steps
# ---------------------------------------------------------------------------

def truncate_all(session: Session) -> None:
    # RESTART IDENTITY resets id sequences to 1; CASCADE handles foreign keys.
    # TRUNCATE does not fire row-level triggers, so no history rows are created here.
    tables = ", ".join(Base.metadata.tables)
    session.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))


def seed_users(session: Session) -> list[dict]:
    """Create admins and customers. Returns customer dicts (id, created_at)."""
    # bcrypt is slow on purpose (that is what makes it secure), so we hash once and reuse
    # the hash for every seed user. Real users always get their own salt.
    password_hash = bcrypt.hashpw(PASSWORD.encode(), bcrypt.gensalt()).decode()

    rows = []
    for i in range(1, N_ADMINS + 1):
        rows.append({
            "name": fake.name(), "email": f"admin{i}@example.com",
            "password_hash": password_hash, "role": "admin",
            "created_at": NOW - timedelta(days=400),
        })
    used_emails = set()
    for _ in range(N_CUSTOMERS):
        name = fake.name()
        base = ".".join(name.lower().replace(".", "").split()[:2])
        email = f"{base}@example.com"
        n = 2
        while email in used_emails:  # two customers with the same name
            email = f"{base}{n}@example.com"
            n += 1
        used_emails.add(email)
        rows.append({
            "name": name, "email": email, "password_hash": password_hash,
            "role": "customer",
            # Customers joined 3-13 months ago, i.e. before any of their orders.
            "created_at": NOW - timedelta(days=rng.randint(100, 400)),
        })

    ids = bulk_insert(session, User, rows, returning_id=True)
    customers = [
        {"id": uid, "created_at": row["created_at"]}
        for uid, row in zip(ids, rows) if row["role"] == "customer"
    ]

    addresses = []
    for c in customers:
        for _ in range(rng.choice([1, 1, 2])):  # most have one address, some have two
            city, state, pin_prefix = rng.choice(CITIES)
            addresses.append({
                "user_id": c["id"], "line1": fake.street_address(), "city": city,
                "state": state, "pincode": f"{pin_prefix}{rng.randint(1, 99):03d}",
            })
    bulk_insert(session, Address, addresses)
    return customers


def seed_catalog(session: Session) -> list[dict]:
    """Create categories, products and inventory. Returns product dicts used later."""
    category_ids = bulk_insert(
        session, Category, [{"name": name} for name in CATALOG], returning_id=True
    )

    product_rows, meta = [], []  # meta = info we need later but don't store (product type)
    for category_id, types in zip(category_ids, CATALOG.values()):
        for ptype in types:
            entries = []  # (name, description, price)
            if "items" in ptype:  # books: explicit titles and blurbs
                for name, description in ptype["items"]:
                    entries.append((name, description, inr_price(*ptype["price"])))
            else:
                for i in range(ptype["count"]):
                    brand = ptype["brands"][i % len(ptype["brands"])]
                    name = f"{brand} {ptype['models'][i]} {ptype['label']}"
                    features = " ".join(rng.sample(ptype["features"], 3))
                    description = (
                        f"The {name} {rng.choice(ptype['pitches'])}. {features} "
                        f"{rng.choice(ptype['uses'])}"
                    )
                    # Types whose price depends on the spec (an i7 laptop must cost more
                    # than an i3) list one price per model; others get a random price.
                    if "prices" in ptype:
                        price = Decimal(ptype["prices"][i])
                    else:
                        price = inr_price(*ptype["price"])
                    entries.append((name, description, price))
            for name, description, price in entries:
                product_rows.append({
                    "category_id": category_id, "name": name, "description": description,
                    "price": price,
                    "created_at": NOW - timedelta(days=rng.randint(120, 365)),
                })
                meta.append({"type": ptype["label"]})

    ids = bulk_insert(session, Product, product_rows, returning_id=True)
    products = [
        {"id": pid, "price": row["price"], "type": m["type"], "active": True}
        for pid, row, m in zip(ids, product_rows, meta)
    ]

    # Soft-delete 3 products: they stay in old orders but are hidden from the shop.
    for p in rng.sample(products, 3):
        p["active"] = False
    inactive_ids = [p["id"] for p in products if not p["active"]]
    session.execute(
        text("UPDATE products SET is_active = false WHERE id = ANY(:ids)"),
        {"ids": inactive_ids},
    )

    # Normal stock levels, plus 7 active products below 10 units (low-stock alerts).
    low_stock = {p["id"] for p in rng.sample([p for p in products if p["active"]], 7)}
    stock_rows = []
    for p in products:
        if p["id"] in low_stock:
            stock = rng.choice([0, 2, 3, 5, 7, 8, 9])
        else:
            stock = rng.randint(15, 150)
        stock_rows.append({"product_id": p["id"], "stock": stock})
    bulk_insert(session, Inventory, stock_rows)
    return products


def seed_coupons(session: Session) -> list[dict]:
    coupons = [
        {"code": "WELCOME10", "percent_off": 10, "valid_until": NOW + timedelta(days=180), "is_active": True},
        {"code": "FESTIVE15", "percent_off": 15, "valid_until": NOW + timedelta(days=30), "is_active": True},
        {"code": "DIWALI25", "percent_off": 25, "valid_until": NOW + timedelta(days=20), "is_active": True},
        # Expired one month ago: only older orders could have used it.
        {"code": "MONSOON20", "percent_off": 20, "valid_until": NOW - timedelta(days=30), "is_active": True},
        # Disabled by an admin; never used.
        {"code": "FLASH50", "percent_off": 50, "valid_until": NOW + timedelta(days=5), "is_active": False},
    ]
    bulk_insert(session, Coupon, coupons)
    return coupons


def random_order_time(customer_joined: datetime) -> datetime:
    """A time in the last 90 days, weighted so recent days are busier."""
    # Weight goes from 1 (90 days ago) up to 3 (today); weekends get a 30% boost.
    days_ago = list(range(DAYS_OF_HISTORY))
    weights = []
    for d in days_ago:
        w = 1 + 2 * (DAYS_OF_HISTORY - d) / DAYS_OF_HISTORY
        if (NOW - timedelta(days=d)).astimezone(IST).weekday() >= 5:
            w *= 1.3
        weights.append(w)
    d = rng.choices(days_ago, weights)[0]

    # Hour of day in India: quiet at night, peak in the evening.
    hour_weights = [1, 1, 1, 1, 1, 1, 2, 3, 4, 5, 6, 6, 7, 7, 6, 6, 6, 7, 8, 10, 11, 10, 7, 3]
    hour = rng.choices(range(24), hour_weights)[0]
    day = (NOW - timedelta(days=d)).astimezone(IST)
    t = day.replace(hour=hour, minute=rng.randint(0, 59), second=rng.randint(0, 59), microsecond=0)
    t = t.astimezone(timezone.utc)
    fallback_minutes = rng.randint(5, 300)  # drawn always, to keep the sequence stable
    if t >= NOW:  # today, but an hour that hasn't happened yet
        t = NOW - timedelta(minutes=fallback_minutes)
    return max(t, customer_joined + timedelta(days=1))


def build_basket(products: list[dict], by_type: dict, popularity: list[float],
                 preferred: dict) -> dict[int, int]:
    """Pick the products for one order. Returns {product_id: qty}."""
    basket: dict[int, int] = {}
    active = [p for p in products if p["active"]]

    # ~40% of orders are built around a "bundle" anchor (phone, laptop, shoes...).
    if rng.random() < 0.40:
        anchor = rng.choice([p for t in BUNDLES for p in by_type[t] if p["active"]])
        basket[anchor["id"]] = 1
        for companion_type, probability in BUNDLES[anchor["type"]]:
            if rng.random() < probability:
                # 80%: the anchor's preferred companion (strong, specific pattern);
                # 20%: any product of that type (realistic noise).
                if rng.random() < 0.8:
                    companion = preferred[(anchor["id"], companion_type)]
                else:
                    companion = rng.choice(by_type[companion_type])
                if companion["active"]:
                    basket[companion["id"]] = 1
        extra_items = rng.choices([0, 1], [0.7, 0.3])[0]
    else:
        extra_items = rng.choices([1, 2, 3, 4], [0.45, 0.30, 0.17, 0.08])[0]

    # Remaining items follow a popularity curve, so some products are clear best-sellers.
    for _ in range(extra_items):
        p = rng.choices(active, popularity)[0]
        basket[p["id"]] = basket.get(p["id"], 0) + rng.choices([1, 2, 3], [0.8, 0.15, 0.05])[0]
    return basket


def seed_orders(session: Session, customers: list[dict], products: list[dict],
                coupons: list[dict]) -> list[dict]:
    """Create orders, items and payments, then move statuses forward via the trigger."""
    by_type = defaultdict(list)
    for p in products:
        by_type[p["type"]].append(p)
    by_id = {p["id"]: p for p in products}

    # Each anchor product gets one preferred companion per companion type.
    preferred = {}
    for anchor_type, companions in BUNDLES.items():
        for i, anchor in enumerate(by_type[anchor_type]):
            for companion_type, _ in companions:
                options = by_type[companion_type]
                preferred[(anchor["id"], companion_type)] = options[i % len(options)]

    # Popularity: a long-tail curve (rank 1 is ~10x more popular than rank 100).
    active = [p for p in products if p["active"]]
    ranks = list(range(1, len(active) + 1))
    rng.shuffle(ranks)
    popularity = [1 / r ** 0.6 for r in ranks]

    # Some customers shop much more often than others.
    customer_weights = [rng.uniform(0.3, 3) for _ in customers]

    plans = []  # one entry per order: everything needed to insert it and its children
    for _ in range(N_ORDERS):
        customer = rng.choices(customers, customer_weights)[0]
        created = random_order_time(customer["created_at"])
        basket = build_basket(products, by_type, popularity, preferred)

        items = []
        for pid, qty in basket.items():
            price = by_id[pid]["price"]
            # Prices changed for some products over time; order_items keeps the old price.
            # (Draw the random number first, unconditionally: if the draw only happened
            # for some orders, the whole random sequence would shift between runs.)
            price_changed = rng.random() < 0.2
            if (NOW - created).days > 30 and price_changed:
                price = money(price * Decimal(str(rng.uniform(0.9, 1.1))))
            items.append({"product_id": pid, "qty": qty, "unit_price": price})
        subtotal = money(sum(i["unit_price"] * i["qty"] for i in items))

        coupon_code, discount = None, Decimal("0.00")
        if rng.random() < 0.2:
            usable = [c for c in coupons if c["is_active"] and c["valid_until"] > created]
            if usable:
                c = rng.choice(usable)
                coupon_code = c["code"]
                discount = money(subtotal * c["percent_off"] / 100)

        # Lifecycle: shipped 0.5-2 days after ordering, delivered 1-5 days after shipping.
        # Whichever of those moments are already in the past decide the current status.
        shipped_at = created + timedelta(hours=rng.uniform(12, 48))
        delivered_at = shipped_at + timedelta(hours=rng.uniform(24, 120))
        transitions = []  # (new_status, when)
        if rng.random() < 0.07:  # ~7% cancelled, usually within hours of ordering
            cancelled_at = created + timedelta(hours=rng.uniform(0.5, 20))
            cancelled_at = min(cancelled_at, created + (NOW - created) / 2)
            transitions.append(("cancelled", cancelled_at))
        else:
            if shipped_at < NOW:
                transitions.append(("shipped", shipped_at))
            if delivered_at < NOW:
                transitions.append(("delivered", delivered_at))

        plans.append({
            "order": {
                "user_id": customer["id"], "status": "placed", "subtotal": subtotal,
                "discount": discount, "total": subtotal - discount,
                "coupon_code": coupon_code, "created_at": created,
            },
            "items": items,
            "transitions": transitions,
        })

    # Insert every order as 'placed' -> the trigger logs (NULL -> placed) for each one.
    order_ids = bulk_insert(session, Order, [p["order"] for p in plans], returning_id=True)

    item_rows, payment_rows = [], []
    for order_id, plan in zip(order_ids, plans):
        plan["id"] = order_id
        item_rows += [{"order_id": order_id, **item} for item in plan["items"]]
        payment_rows.append(build_payment(order_id, plan))
    bulk_insert(session, OrderItem, item_rows)
    bulk_insert(session, Payment, payment_rows)

    advance_statuses(session, plans)
    return plans


def build_payment(order_id: int, plan: dict) -> dict:
    """Mock payment. No card data is ever generated or stored."""
    order = plan["order"]
    final_status = plan["transitions"][-1][0] if plan["transitions"] else "placed"
    method = rng.choices(["upi", "card", "cod", "wallet"], [45, 25, 20, 10])[0]

    if method == "cod":
        # Cash on delivery: money is collected only when the parcel is delivered.
        if final_status == "delivered":
            status, paid_at = "success", plan["transitions"][-1][1]
        elif final_status == "cancelled":
            status, paid_at = "failed", None  # never collected
        else:
            status, paid_at = "pending", None
    else:
        paid_at = order["created_at"] + timedelta(seconds=rng.randint(20, 120))
        status = "refunded" if final_status == "cancelled" else "success"
    return {"order_id": order_id, "method": method, "amount": order["total"],
            "status": status, "paid_at": paid_at}


def advance_statuses(session: Session, plans: list[dict]) -> None:
    """Move orders through their statuses with real UPDATEs so the trigger fires,
    then back-date the history rows the trigger just wrote."""
    # Step 1: bulk status updates, in lifecycle order (placed -> shipped -> delivered).
    for status in ("cancelled", "shipped", "delivered"):
        ids = [p["id"] for p in plans if any(s == status for s, _ in p["transitions"])]
        if ids:
            session.execute(
                text("UPDATE orders SET status = :s WHERE id = ANY(:ids)"),
                {"s": status, "ids": ids},
            )

    # Step 2: the trigger stamped those rows with now(); set the realistic past times.
    order_ids, statuses, times = [], [], []
    for p in plans:
        for status, when in p["transitions"]:
            order_ids.append(p["id"])
            statuses.append(status)
            times.append(when)
    session.execute(
        text("""
            UPDATE order_status_history h
            SET changed_at = v.changed_at
            FROM unnest(CAST(:ids AS int[]), CAST(:statuses AS text[]),
                        CAST(:times AS timestamptz[])) AS v(order_id, new_status, changed_at)
            WHERE h.order_id = v.order_id AND h.new_status = v.new_status
        """),
        {"ids": order_ids, "statuses": statuses, "times": times},
    )


def seed_reviews(session: Session, plans: list[dict], products: list[dict]) -> None:
    """300 reviews, only by customers who actually received the product."""
    by_id = {p["id"]: p for p in products}

    # A few "problem" products get mostly bad reviews, so the Negative badge and the
    # admin's flagged-reviews view have something to show.
    problem_products = {p["id"] for p in rng.sample(products, 8)}

    # Every (customer, product) pair from a delivered order, with its delivery time.
    delivered = {}
    for plan in plans:
        if plan["transitions"] and plan["transitions"][-1][0] == "delivered":
            for item in plan["items"]:
                key = (plan["order"]["user_id"], item["product_id"])
                delivered.setdefault(key, plan["transitions"][-1][1])

    # Problem products first (so they surely get reviews), then a random sample.
    keys = sorted(delivered)  # sorted: dict order must not affect reproducibility
    rng.shuffle(keys)
    keys.sort(key=lambda k: k[1] not in problem_products)
    keys = keys[:N_REVIEWS]

    rows = []
    for user_id, product_id in keys:
        if product_id in problem_products:
            rating = rng.choices([1, 2, 3, 4], [45, 30, 15, 10])[0]
        else:
            rating = rng.choices([5, 4, 3, 2, 1], [38, 32, 15, 8, 7])[0]
        comment = review_text(rating, by_id[product_id]["type"])
        reviewed_at = min(
            delivered[(user_id, product_id)] + timedelta(days=rng.uniform(1, 10)),
            NOW - timedelta(minutes=1),
        )
        rows.append({
            "user_id": user_id, "product_id": product_id, "rating": rating,
            "comment": comment,
            # Left empty on purpose: scripts.backfill_sentiment scores every review with
            # app.ai.sentiment, the same function that scores new reviews in the app.
            "sentiment_score": None,
            "created_at": reviewed_at,
        })
    bulk_insert(session, Review, rows)


def review_text(rating: int, product_type: str) -> str:
    parts = REVIEW_TEXT[rating]
    opener = rng.choice(parts["openers"]).format(t=product_type.lower())
    details = " ".join(rng.sample(parts["details"], rng.choice([1, 2])))
    return f"{opener} {details} {rng.choice(parts['closers'])}"


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def print_summary(session: Session) -> None:
    print("\nRow counts")
    for table in Base.metadata.tables:
        count = session.scalar(text(f"SELECT COUNT(*) FROM {table}"))
        print(f"  {table:<22}{count:>6}")

    print("\nv_sales_by_category")
    for r in session.execute(text(
            "SELECT category, order_count, units_sold, revenue FROM v_sales_by_category "
            "ORDER BY revenue DESC")):
        print(f"  {r.category:<32}{r.order_count:>5} orders {r.units_sold:>5} units  Rs {r.revenue:>12,}")

    print("\nv_top_products (top 5 by revenue)")
    for r in session.execute(text(
            "SELECT revenue_rank, product, units_sold, revenue FROM v_top_products "
            "WHERE revenue_rank <= 5 ORDER BY revenue_rank")):
        print(f"  #{r.revenue_rank} {r.product[:50]:<50}{r.units_sold:>4} units  Rs {r.revenue:>11,}")

    print("\nv_daily_revenue")
    s = session.execute(text(
        "SELECT COUNT(*) AS days, MIN(day) AS first, MAX(day) AS last, SUM(order_count) AS orders, "
        "SUM(revenue) AS revenue FROM v_daily_revenue")).one()
    print(f"  {s.days} days with sales, {s.first} to {s.last}, {s.orders} orders, Rs {s.revenue:,}")
    for r in session.execute(text(
            "SELECT day, order_count, revenue FROM v_daily_revenue ORDER BY day DESC LIMIT 5")):
        print(f"  {r.day}  {r.order_count:>3} orders  Rs {r.revenue:>11,}")

    print("\nv_low_stock")
    for r in session.execute(text(
            "SELECT product, category, stock FROM v_low_stock ORDER BY stock")):
        print(f"  {r.stock:>3} left  {r.product[:50]:<50} ({r.category})")


def main() -> None:
    Faker.seed(SEED)
    with get_session() as session:  # one transaction: all or nothing
        print("Truncating tables...")
        truncate_all(session)
        print("Seeding users, catalog, coupons, orders and reviews...")
        customers = seed_users(session)
        products = seed_catalog(session)
        coupons = seed_coupons(session)
        plans = seed_orders(session, customers, products, coupons)
        seed_reviews(session, plans, products)
    print("Done.")
    with get_session() as session:
        print_summary(session)


if __name__ == "__main__":
    main()
