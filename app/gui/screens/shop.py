"""Shop: the category strip, a "Recommended for you" row (default view only) and a grid
of product tiles. Searching happens in the header's search box (app.header.search);
its results are shown here.

    [ All | Mobiles | Laptops | Home | Clothing | ... ]        <- category strip
    +-------------------------------------------------------+
    | Recommended for you   [tile] [tile] [tile] ... --->   |
    +-------------------------------------------------------+
    | 200 products                                          |
    | [tile] [tile] [tile] [tile] [tile]                    |
    | ...                         < Previous  Page 1  Next >|
    +-------------------------------------------------------+

Tiles are shown 20 per page. CustomTkinter widgets are drawn on canvases and are
fairly heavy; building all ~200 tiles at once would make the screen slow to appear
and use noticeably more memory on a 4 GB laptop.
"""

import logging

import customtkinter as ctk

from app.gui import theme
from app.gui.screens.base import Screen
from app.gui.theme import PAD_L, PAD_M, PAD_S, PAD_XS
from app.gui.widgets.category_strip import CategoryStrip
from app.gui.widgets.common import (
    card, clear, empty_state, label, link_button, muted, section_title,
)
from app.gui.widgets.product_card import ProductCard
from app.services import catalog_service, system_service

PAGE_SIZE = 20
COLUMNS = 5
SEARCH_LIMIT = 40
ALL_CATEGORIES = "All"
FIRST_SEARCH_MESSAGE = "Loading AI model (first search, ~30 s)..."

log = logging.getLogger(__name__)


class ShopScreen(Screen):
    title = "Shop"
    show_title = False  # the category strip is the top of this screen

    def __init__(self, parent, app) -> None:
        super().__init__(parent, app)
        self._categories: dict[str, int] = {}
        self._products = []
        self._page = 0
        self._request = 0   # increases with every load; stale results are ignored
        self._loaded = False
        self._search_query = ""
        self._recommendations = []
        self._rec_cards = []
        # The search box lives in the header (one search box for the whole app).
        self._search = app.header.search

        self._category = CategoryStrip(self, ALL_CATEGORIES,
                                       on_change=lambda _name: self._load_category())
        self._category.pack(fill="x")

        # --- "Recommended for you": a white panel with one horizontal, scrollable row
        # of compact tiles. Packed only on the default view (see _update_recommended).
        self._recommended = card(self)
        section_title(self._recommended, "Recommended for you").pack(
            fill="x", padx=PAD_L, pady=(PAD_M, PAD_XS))
        self._rec_row = ctk.CTkScrollableFrame(self._recommended, orientation="horizontal",
                                               fg_color="transparent", height=200)
        self._rec_row.pack(fill="x", padx=PAD_S, pady=(0, PAD_S))

        # --- Results panel: summary line, the grid, and the pager.
        self._results = card(self)
        self._results.pack(fill="both", expand=True, padx=PAD_M, pady=(PAD_S, PAD_M))

        # "Showing results for shirt  ·  Search instead for sirt" (only after a correction).
        self._correction = ctk.CTkFrame(self._results, fg_color="transparent")
        label(self._correction, "Showing results for", size=13).pack(side="left")
        self._corrected_label = label(self._correction, "", size=13, weight="bold")
        self._corrected_label.pack(side="left", padx=(5, 0))
        self._original_link = link_button(self._correction, "", self._search_original)
        self._original_link.pack(side="left", padx=(PAD_S, 0))
        self._original_query = ""

        self._summary_row = ctk.CTkFrame(self._results, fg_color="transparent")
        self._summary_row.pack(fill="x", padx=PAD_L, pady=(PAD_M, 0))
        self._summary = label(self._summary_row, "", size=13, weight="bold")
        self._summary.pack(side="left")
        self._clear_button = link_button(self._summary_row, f"{theme.ICONS['close']}  "
                                         "Clear search", self._clear_search)
        self._clear_button.configure(font=theme.font(12, "bold"))

        # Pager at the bottom (packed before the grid so the grid can't squeeze it out).
        pager = ctk.CTkFrame(self._results, fg_color="transparent")
        pager.pack(side="bottom", fill="x", padx=PAD_L, pady=PAD_S)
        self._prev = ctk.CTkButton(pager, text="PREVIOUS", width=100,
                                   command=lambda: self._show_page(self._page - 1),
                                   **theme.secondary_button_style())
        self._next = ctk.CTkButton(pager, text="NEXT", width=100,
                                   command=lambda: self._show_page(self._page + 1),
                                   **theme.secondary_button_style())
        self._page_label = muted(pager, "", size=12)
        self._next.pack(side="right")
        self._page_label.pack(side="right", padx=PAD_M)
        self._prev.pack(side="right")

        # height = the MINIMUM it asks for; it still expands to fill the panel. Kept
        # small so that with the recommended row shown, the grid shrinks instead.
        self._grid = ctk.CTkScrollableFrame(self._results, fg_color="transparent", height=120)
        self._grid.pack(fill="both", expand=True, padx=PAD_S, pady=(PAD_S, 0))
        for column in range(COLUMNS):
            self._grid.grid_columnconfigure(column, weight=1, uniform="cards")

    # ------------------------------------------------------------------ loading

    def on_show(self, search: str | None = None, **kwargs) -> None:
        """search: a query typed in the header (the box already holds the text)."""
        # Keep the current results and page when coming back from a product page.
        if not self._loaded:
            self._loaded = True
            self.app.tasks.run(catalog_service.list_categories,
                               on_success=self._set_categories, message="Loading categories...")
            if not search:
                self._load_category()
        if search:
            self._run_search()
        # Recommendations are fetched every time (one small query): after an order they
        # change, and a product just bought must not stay in the row.
        self.app.tasks.run(catalog_service.recommended_for_you, self.app.user,
                           on_success=self._set_recommendations,
                           on_error=self._recommendations_failed,
                           message="Loading recommendations...")

    def _set_categories(self, categories) -> None:
        self._categories = {c.name: c.id for c in categories}
        self._category.set_categories(list(self._categories))

    def _load_category(self) -> None:
        self._search_query = ""
        self._search.delete(0, "end")
        self._clear_button.pack_forget()
        category_id = self._categories.get(self._category.get())
        self._start(catalog_service.browse_products, category_id, message="Loading products...")

    def _run_search(self, correct_spelling: bool = True) -> None:
        query = self._search.get().strip()
        if not query:
            return
        self._search_query = query
        self._category.set(ALL_CATEGORIES)  # search covers every category
        self._clear_button.pack(side="left", padx=(PAD_M, 0))
        message = ("Searching..." if system_service.is_search_model_loaded()
                   else FIRST_SEARCH_MESSAGE)
        self._start(catalog_service.search, query, SEARCH_LIMIT, correct_spelling,
                    message=message)

    def _search_original(self) -> None:
        """The "Search instead for <typed words>" link: search without correcting."""
        self._search.delete(0, "end")
        self._search.insert(0, self._original_query)
        self._run_search(correct_spelling=False)

    def _clear_search(self) -> None:
        self._category.set(ALL_CATEGORIES)
        self._load_category()

    def _start(self, func, *args, message: str) -> None:
        self._request += 1
        request = self._request
        self._summary.configure(text="")
        self._show_correction(None)
        self._update_recommended()
        self.app.tasks.run(func, *args, message=message,
                           on_success=lambda products: self._loaded_products(request, products))

    def _loaded_products(self, request: int, result) -> None:
        if request != self._request:
            return  # the user started another search / filter meanwhile
        if self._search_query:  # catalog_service.search returns SearchResults
            products = result.products
            self._show_correction(result)
            searched = result.corrected_query or result.query
            text = f"{len(products)} results for \"{searched}\", best match first"
        else:                   # browse_products returns a plain list
            products = result
            category = self._category.get()
            text = (f"{len(products)} products" if category == ALL_CATEGORIES
                    else f"{category}  ·  {len(products)} products")
        self._products = products
        self._summary.configure(text=text)
        self._show_page(0)

    # ------------------------------------------------------------------ recommendations

    def _set_recommendations(self, products) -> None:
        if [p.id for p in products] != [p.id for p in self._recommendations]:
            self._recommendations = products
            self._render_recommendations()
        self._update_recommended()

    def _recommendations_failed(self, error) -> None:
        # A nice-to-have row: if it can't load, the shop works without it; no popup.
        log.warning("Could not load recommendations: %s", error)
        self._recommendations = []
        self._update_recommended()

    def _is_default_view(self) -> bool:
        return not self._search_query and self._category.get() == ALL_CATEGORIES

    def _update_recommended(self) -> None:
        """Show the row only on the default view (no search, all categories)."""
        if self._recommendations and self._is_default_view():
            self._recommended.pack(fill="x", padx=PAD_M, pady=(PAD_S, 0),
                                   before=self._results)
        else:
            self._recommended.pack_forget()

    def _render_recommendations(self) -> None:
        clear(self._rec_row)
        # Same width as a tile in the grid below, so the two line up.
        scale = ctk.ScalingTracker.get_widget_scaling(self)
        column = max(self._grid.winfo_width() // COLUMNS, int(190 * scale))
        self._rec_cards = []
        for index, product in enumerate(self._recommendations):
            self._rec_row.grid_columnconfigure(index, minsize=column, uniform="rec")
            card = ProductCard(self._rec_row, product, on_open=self._open, compact=True)
            card.grid(row=0, column=index, sticky="nsew", padx=PAD_XS, pady=(0, PAD_XS))
            # Names re-wrap once the tiles get their real width, which changes their
            # height; re-fit the row each time that happens.
            card.bind("<Configure>", lambda _e: self._fit_row_height(), add="+")
            self._rec_cards.append(card)
        self._fit_row_height()

    def _fit_row_height(self) -> None:
        """A horizontal scroll area needs a fixed height: make it the tallest tile's."""
        cards = [c for c in self._rec_cards if c.winfo_exists()]
        if not cards:
            return
        self._rec_row.update_idletasks()
        scale = ctk.ScalingTracker.get_widget_scaling(self)
        height = int(max(c.winfo_reqheight() for c in cards) / scale) + PAD_S
        if height != self._rec_row.cget("height"):
            self._rec_row.configure(height=height)

    # ------------------------------------------------------------------ display

    def _show_correction(self, result) -> None:
        """Show the "Showing results for ..." line if the search fixed a typo."""
        if result is None or not result.corrected_query:
            self._correction.pack_forget()
            return
        self._original_query = result.query
        self._corrected_label.configure(text=result.corrected_query)
        self._original_link.configure(text=f"Search instead for {result.query}")
        self._correction.pack(fill="x", padx=PAD_L, pady=(PAD_M, 0), before=self._summary_row)

    def _show_page(self, page: int) -> None:
        pages = max(1, -(-len(self._products) // PAGE_SIZE))  # ceiling division
        self._page = min(max(page, 0), pages - 1)
        clear(self._grid)
        shown = self._products[self._page * PAGE_SIZE:(self._page + 1) * PAGE_SIZE]
        if not shown:
            empty = ctk.CTkFrame(self._grid, fg_color="transparent")
            empty.grid(row=0, column=0, columnspan=COLUMNS, sticky="w", padx=PAD_S,
                       pady=PAD_L)
            label(empty, "Sorry, no results found!", size=16, weight="bold").pack(fill="x")
            empty_state(empty, "Please check the spelling, try more general words, or "
                               "pick another category.").pack(fill="x", pady=(2, 0))
        for index, product in enumerate(shown):
            ProductCard(self._grid, product, on_open=self._open).grid(
                row=index // COLUMNS, column=index % COLUMNS, sticky="nsew",
                padx=PAD_XS, pady=PAD_XS)
        self._grid._parent_canvas.yview_moveto(0)  # back to the top of the list
        self._page_label.configure(text=f"Page {self._page + 1} of {pages}")
        self._prev.configure(state="normal" if self._page > 0 else "disabled")
        self._next.configure(state="normal" if self._page < pages - 1 else "disabled")

    def _open(self, product_id: int) -> None:
        self.app.navigate("product", product_id=product_id, back_to="shop")
