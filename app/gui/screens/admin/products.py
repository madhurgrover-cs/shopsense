"""Admin products: a searchable table of ALL products (soft-deleted ones too), with
add, edit, update stock, delete (soft) and restore.

Every change is a catalog_service call, which validates the input (clear error popup
if something is wrong), writes the change and its audit-log entry in one transaction.
"""

from app.gui import formatting as fmt
from app.gui.screens.admin.common import button, dropdown, search_box, set_enabled, toolbar
from app.gui.screens.base import Screen
from app.gui.theme import PAD_L, PAD_S, PAD_XL
from app.gui.widgets.common import muted
from app.gui.widgets.dialogs import Field, FormDialog
from app.gui.widgets.table import Column, DataTable
from app.services import catalog_service
from app.services.dto import ProductDetail, ProductSummary

LOW_STOCK = 10  # same rule as the v_low_stock view
ALL_CATEGORIES = "All categories"
SHOW = ["All products", "Active", "Deleted", "Low stock"]


def product_status(product: ProductSummary) -> str:
    if not product.is_active:
        return "Deleted"
    if product.stock == 0:
        return "Out of stock"
    if product.stock < LOW_STOCK:
        return "Low stock"
    return "Active"


def matches(product: ProductSummary, text: str, category: str, show: str) -> bool:
    """The in-memory filter behind the search box and drop-downs."""
    if text and text not in f"{product.id} {product.name} {product.category}".lower():
        return False
    if category != ALL_CATEGORIES and product.category != category:
        return False
    if show == "Active":
        return product.is_active
    if show == "Deleted":
        return not product.is_active
    if show == "Low stock":
        return product.is_active and product.stock < LOW_STOCK
    return True


class ProductsScreen(Screen):
    title = "Products"

    def __init__(self, parent, app) -> None:
        super().__init__(parent, app)
        self._products: list[ProductSummary] = []
        self._categories: dict[str, int] = {}  # name -> id

        bar = toolbar(self)
        self._search = search_box(bar, "Search by name, category or ID", self._filter)
        self._search.pack(side="left")
        self._category = dropdown(bar, [ALL_CATEGORIES], lambda _v: self._filter(), width=230)
        self._category.pack(side="left", padx=PAD_S)
        self._show = dropdown(bar, SHOW, lambda _v: self._filter(), width=150)
        self._show.pack(side="left")
        button(bar, "+ Add product", self._add, kind="primary", width=140).pack(side="right")

        actions = toolbar(self)
        self._count = muted(actions, "")
        self._count.pack(side="left")
        self._restore = button(actions, "Restore", self._restore_selected, width=100)
        self._delete = button(actions, "Delete", self._delete_selected, kind="danger", width=100)
        self._stock = button(actions, "Update stock", self._update_stock, width=130)
        self._edit = button(actions, "Edit", self._edit_selected, width=90)
        for widget in (self._restore, self._delete, self._stock, self._edit):
            widget.pack(side="right", padx=(PAD_S, 0))

        self.table = DataTable(self, [
            Column("ID", 60, lambda p: p.id, sort=lambda p: p.id, anchor="e"),
            Column("Name", 360, lambda p: p.name),
            Column("Category", 210, lambda p: p.category),
            Column("Price", 110, lambda p: fmt.inr(p.price), sort=lambda p: p.price, anchor="e"),
            Column("Stock", 80, lambda p: p.stock, sort=lambda p: p.stock, anchor="e"),
            Column("Status", 110, product_status),
            Column("Rating", 100, lambda p: fmt.rating(p.avg_rating, p.review_count)
                   if p.review_count else "-", sort=lambda p: p.avg_rating),
        ], on_select=lambda _p: self._update_buttons(), on_open=lambda _p: self._edit_selected(),
            row_color=self._row_color, empty_text="No products match.")
        self.table.pack(fill="both", expand=True, padx=PAD_XL, pady=(0, PAD_L))
        self._update_buttons()

    @staticmethod
    def _row_color(product: ProductSummary) -> str | None:
        if not product.is_active:
            return "text_muted"
        if product.stock == 0:
            return "danger"
        if product.stock < LOW_STOCK:
            return "warning"
        return None

    # ------------------------------------------------------------------ loading

    def on_show(self, show: str | None = None, **kwargs) -> None:
        if show in SHOW:  # e.g. the dashboard's low-stock card
            self._show.set(show)
        self.app.tasks.run(catalog_service.list_categories, on_success=self._set_categories,
                           message="Loading categories...")
        self._reload()

    def _reload(self, select_id: int | None = None) -> None:
        def loaded(products) -> None:
            self._products = products
            self._filter()
            if select_id is not None:
                self.table.select(select_id)
            self._update_buttons()
        self.app.tasks.run(catalog_service.list_all_products, self.app.user,
                           on_success=loaded, message="Loading products...")

    def _set_categories(self, categories) -> None:
        self._categories = {c.name: c.id for c in categories}
        self._category.configure(values=[ALL_CATEGORIES, *self._categories])

    def _filter(self) -> None:
        text = self._search.get().strip().lower()
        shown = [p for p in self._products
                 if matches(p, text, self._category.get(), self._show.get())]
        self.table.set_items(shown, key=lambda p: p.id)
        self._count.configure(text=f"{len(shown)} of {len(self._products)} products")
        self._update_buttons()

    def _update_buttons(self) -> None:
        product = self.table.selected
        for widget in (self._edit, self._stock):
            set_enabled(widget, product is not None)
        set_enabled(self._delete, product is not None and product.is_active)
        set_enabled(self._restore, product is not None and not product.is_active)

    # ------------------------------------------------------------------ add / edit

    def _product_fields(self, product: ProductDetail | None) -> list[Field]:
        categories = list(self._categories)
        fields = [
            Field("name", "Name", product.name if product else ""),
            Field("category", "Category", product.category if product else "",
                  kind="choice", choices=categories),
            Field("price", "Price (₹)", f"{product.price}" if product else "",
                  hint="e.g. 1299 or 1299.50"),
        ]
        if product is None:  # stock of an existing product is changed with "Update stock"
            fields.append(Field("stock", "Opening stock", "0", hint="Whole number, 0 or more"))
        fields.append(Field("description", "Description",
                            product.description if product else "", kind="text"))
        return fields

    def _add(self) -> None:
        FormDialog(self.app, "Add product", self._product_fields(None), self._save_new,
                   submit_text="Add product")

    def _save_new(self, dialog: FormDialog, values: dict) -> None:
        category_id = self._categories.get(values["category"], 0)

        def saved(product: ProductDetail) -> None:
            dialog.destroy()
            self.app.show_message("Product added", f"{product.name} was added.", kind="success")
            self._reload(select_id=product.id)

        self._run_form(dialog, catalog_service.create_product, self.app.user, category_id,
                       values["name"], values["description"], values["price"], values["stock"],
                       on_success=saved, message="Adding product...")

    def _edit_selected(self) -> None:
        product = self.table.selected
        if product is None:
            return
        # The table has no descriptions (they're long), so fetch the full product first.
        self.app.tasks.run(catalog_service.get_product_detail, product.id,
                           on_success=self._open_editor, message="Loading product...")

    def _open_editor(self, product: ProductDetail) -> None:
        def save(dialog: FormDialog, values: dict) -> None:
            def saved(updated: ProductDetail) -> None:
                dialog.destroy()
                self.app.show_message("Product saved", f"{updated.name} was updated.",
                                      kind="success")
                self._reload(select_id=updated.id)

            # Every field is sent; the service only changes (and audits) what differs.
            self._run_form(dialog, catalog_service.update_product, self.app.user, product.id,
                           name=values["name"], description=values["description"],
                           price=values["price"],
                           category_id=self._categories.get(values["category"], 0),
                           on_success=saved, message="Saving product...")

        FormDialog(self.app, f"Edit product #{product.id}", self._product_fields(product), save)

    def _run_form(self, dialog: FormDialog, func, *args, on_success, message: str,
                  **kwargs) -> None:
        """Run a service call for a form; on an error show it and keep the form open."""
        def failed(error) -> None:
            self.app.show_error(error)
            dialog.failed()
        self.app.tasks.run(func, *args, on_success=on_success, on_error=failed,
                           message=message, **kwargs)

    # ------------------------------------------------------------------ stock / delete

    def _update_stock(self) -> None:
        product = self.table.selected
        if product is None:
            return

        def save(dialog: FormDialog, values: dict) -> None:
            def saved(new_stock: int) -> None:
                dialog.destroy()
                self.app.show_message("Stock updated",
                                      f"{product.name}: {product.stock} → {new_stock} in stock.",
                                      kind="success")
                self._reload(select_id=product.id)
            self._run_form(dialog, catalog_service.update_stock, self.app.user, product.id,
                           values["stock"], on_success=saved, message="Updating stock...")

        FormDialog(self.app, "Update stock", [
            Field("stock", f"New stock for {product.name}", str(product.stock),
                  hint=f"Currently {product.stock} in stock. Whole number, 0 or more."),
        ], save, submit_text="Update")

    def _delete_selected(self) -> None:
        product = self.table.selected
        if product is None or not product.is_active:
            return

        def delete() -> None:
            self.app.tasks.run(catalog_service.delete_product, self.app.user, product.id,
                               on_success=lambda _r: self._reload(select_id=product.id),
                               message="Deleting product...")

        self.app.confirm("Delete product?",
                         f"{product.name} will be hidden from the shop. Past orders keep "
                         "showing it, and you can restore it later.",
                         delete, confirm_text="Delete")

    def _restore_selected(self) -> None:
        product = self.table.selected
        if product is None or product.is_active:
            return
        self.app.tasks.run(catalog_service.restore_product, self.app.user, product.id,
                           on_success=lambda _r: self._reload(select_id=product.id),
                           message="Restoring product...")

