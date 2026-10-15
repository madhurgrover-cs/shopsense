"""Shop: category filter, search (with spelling correction), and a grid of product cards.

Cards are shown 24 per page. CustomTkinter widgets are drawn on canvases and are
fairly heavy; building all ~200 cards at once would make the screen slow to appear
and use noticeably more memory on a 4 GB laptop.
"""

import customtkinter as ctk

from app.gui import theme
from app.gui.screens.base import Screen
from app.gui.theme import COLORS, CORNER_RADIUS, PAD_L, PAD_M, PAD_S, PAD_XL
from app.gui.widgets.common import clear, empty_state, form_entry, label, link_button, muted
from app.gui.widgets.product_card import ProductCard
from app.services import catalog_service, system_service

PAGE_SIZE = 24
COLUMNS = 4
SEARCH_LIMIT = 40
ALL_CATEGORIES = "All categories"
FIRST_SEARCH_MESSAGE = "Loading AI model (first search, ~30 s)..."


class ShopScreen(Screen):
    title = "Shop"

    def __init__(self, parent, app) -> None:
        super().__init__(parent, app)
        self._categories: dict[str, int] = {}
        self._products = []
        self._page = 0
        self._request = 0   # increases with every load; stale results are ignored
        self._loaded = False
        self._search_query = ""

        # --- Toolbar: search box, search button, category filter.
        toolbar = ctk.CTkFrame(self, fg_color="transparent")
        toolbar.pack(fill="x", padx=PAD_XL, pady=(PAD_S, PAD_M))
        self._search = form_entry(toolbar, "Describe what you need, e.g. \"gift for a gamer\"")
        self._search.configure(width=460, fg_color=COLORS["surface"])
        self._search.pack(side="left")
        self._search.bind("<Return>", lambda _e: self._run_search())
        ctk.CTkButton(toolbar, text="Search", width=96, command=self._run_search,
                      **theme.primary_button_style()).pack(side="left", padx=PAD_S)
        self._clear_button = ctk.CTkButton(toolbar, text="Clear", width=80,
                                           command=self._clear_search,
                                           **theme.secondary_button_style())

        self._category = ctk.CTkOptionMenu(
            toolbar, values=[ALL_CATEGORIES], command=lambda _v: self._load_category(),
            width=230, height=38, corner_radius=CORNER_RADIUS, font=theme.body_font(),
            fg_color=COLORS["surface"], button_color=COLORS["surface_hover"],
            button_hover_color=COLORS["border"], text_color=COLORS["text"],
            dropdown_fg_color=COLORS["surface"], dropdown_text_color=COLORS["text"],
            dropdown_font=theme.body_font())
        self._category.pack(side="right")

        # "Showing results for shirt  ·  Search instead for sirt" (only after a correction).
        self._correction = ctk.CTkFrame(self, fg_color="transparent")
        label(self._correction, "Showing results for", size=14).pack(side="left")
        self._corrected_label = label(self._correction, "", size=14, weight="bold")
        self._corrected_label.pack(side="left", padx=(5, 0))
        self._original_link = link_button(self._correction, "", self._search_original)
        self._original_link.pack(side="left", padx=(PAD_S, 0))
        self._original_query = ""

        self._summary = muted(self, "")
        self._summary.pack(fill="x", padx=PAD_XL)

        # --- Grid of cards.
        self._grid = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self._grid.pack(fill="both", expand=True, padx=PAD_L, pady=(PAD_S, 0))
        for column in range(COLUMNS):
            self._grid.grid_columnconfigure(column, weight=1, uniform="cards")

        # --- Pager.
        pager = ctk.CTkFrame(self, fg_color="transparent")
        pager.pack(fill="x", padx=PAD_XL, pady=PAD_M)
        self._prev = ctk.CTkButton(pager, text="← Previous", width=120,
                                   command=lambda: self._show_page(self._page - 1),
                                   **theme.secondary_button_style())
        self._next = ctk.CTkButton(pager, text="Next →", width=120,
                                   command=lambda: self._show_page(self._page + 1),
                                   **theme.secondary_button_style())
        self._page_label = muted(pager, "")
        self._prev.pack(side="left")
        self._next.pack(side="right")
        self._page_label.pack(side="left", expand=True)

    # ------------------------------------------------------------------ loading

    def on_show(self, **kwargs) -> None:
        # Keep the current results and page when coming back from a product page.
        if not self._loaded:
            self._loaded = True
            self.app.tasks.run(catalog_service.list_categories,
                               on_success=self._set_categories, message="Loading categories...")
            self._load_category()

    def _set_categories(self, categories) -> None:
        self._categories = {f"{c.name} ({c.product_count})": c.id for c in categories}
        self._category.configure(values=[ALL_CATEGORIES, *self._categories])

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
        self._clear_button.pack(side="left")
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
            text = f"{len(products)} products"
        self._products = products
        self._summary.configure(text=text)
        self._show_page(0)

    # ------------------------------------------------------------------ display

    def _show_correction(self, result) -> None:
        """Show the "Showing results for ..." line if the search fixed a typo."""
        if result is None or not result.corrected_query:
            self._correction.pack_forget()
            return
        self._original_query = result.query
        self._corrected_label.configure(text=result.corrected_query)
        self._original_link.configure(text=f"Search instead for {result.query}")
        self._correction.pack(fill="x", padx=PAD_XL, before=self._summary)

    def _show_page(self, page: int) -> None:
        pages = max(1, -(-len(self._products) // PAGE_SIZE))  # ceiling division
        self._page = min(max(page, 0), pages - 1)
        clear(self._grid)
        shown = self._products[self._page * PAGE_SIZE:(self._page + 1) * PAGE_SIZE]
        if not shown:
            empty_state(self._grid, "No products found. Try different words or another "
                                    "category.").grid(row=0, column=0, columnspan=COLUMNS,
                                                      sticky="w", padx=PAD_S, pady=PAD_M)
        for index, product in enumerate(shown):
            ProductCard(self._grid, product, on_open=self._open).grid(
                row=index // COLUMNS, column=index % COLUMNS, sticky="nsew",
                padx=PAD_S, pady=PAD_S)
        self._grid._parent_canvas.yview_moveto(0)  # back to the top of the list
        self._page_label.configure(text=f"Page {self._page + 1} of {pages}")
        self._prev.configure(state="normal" if self._page > 0 else "disabled")
        self._next.configure(state="normal" if self._page < pages - 1 else "disabled")

    def _open(self, product_id: int) -> None:
        self.app.navigate("product", product_id=product_id, back_to="shop")
