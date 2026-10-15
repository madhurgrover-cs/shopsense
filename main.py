"""ShopSense entry point.   Run:  venv\\Scripts\\python main.py

Startup is kept light on purpose (4 GB RAM laptop): nothing here loads the AI model.
The database connection is opened in the background once the window is visible, and
the embedding model only loads on the first search.
"""

import logging
import sys


def main() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        from app.gui.app import ShopSenseApp
    except RuntimeError as error:
        # Most likely DATABASE_URL is missing (raised by app.config); a GUI popup can't
        # be shown yet, so print a clear message instead of a stack trace.
        print(f"ShopSense could not start: {error}", file=sys.stderr)
        sys.exit(1)
    ShopSenseApp().mainloop()


if __name__ == "__main__":
    main()
