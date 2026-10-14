# ShopSense — AI-Powered Online Store Database

SRM Insider AIML onboarding project (Group 2). Final review: **21 Oct 2026** — each member is
evaluated on their understanding of and contribution to the code, so keep code readable and
explainable. Prefer clear, well-commented code over clever code.

## Team ownership
- **Madhur** — database (schema, migrations, triggers, views, seed data), cart/checkout/orders, AI module
- **[Teammate]** — auth + role-based access, GUI screens, admin dashboard, reports
- Work on feature branches (`feat/<module>`), merge to `main` via pull requests.

## Stack
- Python 3.11+
- PostgreSQL hosted on **Neon** (free tier) with the **pgvector** extension — no local DB install
- SQLAlchemy 2.0 ORM (typed `Mapped[]` style) + Alembic migrations
- CustomTkinter GUI, matplotlib charts embedded via `FigureCanvasTkAgg`
- bcrypt for password hashing
- AI: sentence-transformers `all-MiniLM-L6-v2` (CPU only), vaderSentiment
- Faker for seed data, pytest for tests, python-dotenv for config
- Dev machine has **4 GB RAM** (Windows): keep memory use low. Load the embedding model lazily,
  once, and only when needed. Never load it at app startup.

## Architecture rule (do not break)
```
gui/  →  services/  →  repositories/  →  models/ (SQLAlchemy)  →  PostgreSQL
                ↑
              ai/
```
- GUI code never imports SQLAlchemy or touches a session. It only calls services.
- Services hold business logic and own transactions.
- Repositories hold all queries.
- AI module is called from services only.

## Folder layout
```
shopsense/
  app/
    config.py          # loads .env (DATABASE_URL)
    db.py              # engine + session factory
    models/            # one file per area: user.py, catalog.py, cart.py, order.py, review.py
    repositories/
    services/          # auth_service, catalog_service, cart_service, order_service, report_service
    ai/                # embeddings.py, search.py, recommend.py, sentiment.py
    gui/               # app.py (main window), screens/, widgets/
  migrations/          # alembic
  scripts/seed.py
  tests/
  main.py
  .env.example
  requirements.txt
```

## Database schema
- `users` (id, name, email unique, password_hash, role CHECK in ('admin','customer'),
  failed_logins, locked_until, created_at)
- `addresses` (user_id FK, line1, city, state, pincode)
- `audit_log` (user_id, action, entity, entity_id, created_at)
- `categories` (id, name unique)
- `products` (id, category_id FK, name, description, price CHECK > 0, is_active for soft delete, created_at)
- `inventory` (product_id PK/FK, stock CHECK >= 0)
- `product_embeddings` (product_id PK/FK, embedding vector(384))
- `carts` (id, user_id unique FK), `cart_items` (cart_id, product_id, qty CHECK > 0, unique(cart_id, product_id))
- `coupons` (code unique, percent_off CHECK 1–90, valid_until, is_active)
- `orders` (id, user_id, status CHECK in ('placed','shipped','delivered','cancelled'),
  subtotal, discount, total, coupon_code, created_at)
- `order_items` (order_id, product_id, qty, unit_price — price copied at purchase time)
- `order_status_history` (order_id, old_status, new_status, changed_at) — filled by trigger
- `payments` (order_id, method, amount, status, paid_at) — mock only, never store card data
- `reviews` (user_id, product_id, rating CHECK 1–5, comment, sentiment_score, created_at,
  unique(user_id, product_id))

Indexes on all FKs, `products(category_id)`, `orders(user_id, created_at)`, `products(name)`.

### Database features to implement (these are graded talking points)
1. **Checkout is one transaction**: lock inventory rows with `SELECT ... FOR UPDATE`
   (`with_for_update()`), check stock, decrement, create order + items + payment, clear cart.
   Any failure rolls back everything.
2. **Trigger** `trg_order_status` logs every status change into `order_status_history`.
3. **Views**: `v_sales_by_category`, `v_top_products`, `v_daily_revenue`, `v_low_stock`.
4. CHECK constraints and soft delete as above.
Write triggers/views as raw SQL inside Alembic migrations (`op.execute`).

## Features
- Register / login, bcrypt, lock account 15 min after 5 failed logins, role-based screens
- Admin: product CRUD, stock updates, order status updates, coupon management, user list
- Customer: browse by category, search, product page (reviews + recommendations), cart, checkout
  with coupon, order history with status timeline, write review
- Reports: sales by category, top products, revenue trend — export CSV and PDF
- Admin dashboard: KPI cards (revenue, orders, customers, low stock) + matplotlib charts

## AI features
- **Semantic search**: embed `name + description` with MiniLM, store in pgvector, query with
  cosine distance (`<=>`). Fall back to ILIKE keyword search if embeddings are missing.
- **Recommendations**: "frequently bought together" = co-occurrence counts from `order_items`
  (SQL self-join); "similar products" = nearest neighbours in pgvector.
- **Review sentiment**: VADER compound score saved on each review; product badge
  (Positive / Mixed / Negative); admin view of flagged reviews (score < -0.3).
- Stretch (only if core is done): low-stock forecast from sales rate; ask-your-data (NL → SQL,
  read-only DB user).

## Seed data
`scripts/seed.py`: 2 admins, 50 customers, 8 categories, 200 products with realistic
descriptions, 500 orders spread over the last 90 days with status history, 300 reviews with a
mix of positive and negative text, 5 coupons. Password for all seed users: `password123`.
Seed must be re-runnable (truncate first).

## Conventions
- Never commit `.env`. Provide `.env.example`.
- Every service function has a pytest test. Tests use a separate schema or rollback fixture.
- Build one module at a time; run `pytest` before moving on.
- Explain non-obvious decisions in short comments — teammates must be able to defend the code.

- Never run git commands (add, commit, branch, push). The user handles all git.