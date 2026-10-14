# ShopSense

AI-powered online store database: PostgreSQL (Neon + pgvector), SQLAlchemy 2.0, Alembic,
CustomTkinter GUI. See `CLAUDE.md` for the full design, schema and team ownership.

## Setup

Requires **Python 3.11+** (developed on 3.14).

1. **Create and activate a virtual environment** in the project root:

   ```powershell
   py -3.14 -m venv venv
   .\venv\Scripts\Activate.ps1        # macOS/Linux: source venv/bin/activate
   ```

2. **Install the CPU-only build of PyTorch first.** This step is required:

   ```powershell
   pip install torch --index-url https://download.pytorch.org/whl/cpu
   ```

   `sentence-transformers` depends on torch. If you skip this step, `pip` gets torch
   from PyPI, which on Linux is the CUDA build (several GB of GPU libraries we never
   use). The CPU build is much smaller and is all the MiniLM embedding model needs.
   Because torch is already installed, step 3 will not replace it.

3. **Install the remaining requirements:**

   ```powershell
   pip install -r requirements.txt
   ```

   Check it worked: `python -c "import torch; print(torch.__version__)"` should end in `+cpu`.

4. **Configure the database.** Copy `.env.example` to `.env` and set `DATABASE_URL` to
   your Neon connection string. The plain `postgresql://...` URL from the Neon dashboard
   works; `app/config.py` switches it to the psycopg 3 driver. **Never commit `.env`.**

5. **Create the schema** (tables, pgvector extension, trigger, views):

   ```powershell
   alembic upgrade head
   python -m scripts.check_db         # lists tables, views, trigger, pgvector version
   alembic check                      # should print "No new upgrade operations detected."
   ```

6. **Load demo data and build the search embeddings:**

   ```powershell
   python -m scripts.seed                # re-runnable; wipes and refills every table
   python -m scripts.build_embeddings    # needed after every seed (the seed clears embeddings)
   python -m scripts.backfill_sentiment  # scores the seeded reviews with VADER
   ```

   The first `build_embeddings` run downloads the MiniLM model (~90 MB). Later runs
   only embed products that are new or whose name/description changed.
