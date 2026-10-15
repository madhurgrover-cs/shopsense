"""Admin: customer accounts with order count and total spent. Read-only."""

from app.gui import formatting as fmt
from app.gui.screens.admin.common import search_box, toolbar
from app.gui.screens.base import Screen
from app.gui.theme import PAD_L, PAD_XL
from app.gui.widgets.common import muted
from app.gui.widgets.table import Column, DataTable
from app.services import user_service
from app.services.dto import CustomerSummary


class CustomersScreen(Screen):
    title = "Customers"

    def __init__(self, parent, app) -> None:
        super().__init__(parent, app)
        self._customers: list[CustomerSummary] = []
        bar = toolbar(self)
        self._search = search_box(bar, "Search by name or email", self._filter)
        self._search.pack(side="left")
        self._count = muted(bar, "")
        self._count.pack(side="right")

        self.table = DataTable(self, [
            Column("Name", 200, lambda c: c.name),
            Column("Email", 260, lambda c: c.email),
            Column("Joined", 120, lambda c: fmt.day(c.joined_at), sort=lambda c: c.joined_at),
            Column("Orders", 80, lambda c: c.order_count, sort=lambda c: c.order_count,
                   anchor="e"),
            Column("Total spent", 130, lambda c: fmt.inr(c.total_spent),
                   sort=lambda c: c.total_spent, anchor="e"),
            Column("Last order", 120, lambda c: fmt.day(c.last_order_at) if c.last_order_at
                   else "-", sort=lambda c: c.last_order_at),
            Column("Account", 100, lambda c: "Locked" if c.is_locked else "Active"),
        ], row_color=lambda c: "danger" if c.is_locked else None,
            empty_text="No customers match.")
        self.table.pack(fill="both", expand=True, padx=PAD_XL, pady=(0, PAD_L))

    def on_show(self, **kwargs) -> None:
        self.app.tasks.run(user_service.list_customers, self.app.user,
                           on_success=self._loaded, message="Loading customers...")

    def _loaded(self, customers: list[CustomerSummary]) -> None:
        self._customers = customers
        self._filter()

    def _filter(self) -> None:
        text = self._search.get().strip().lower()
        shown = [c for c in self._customers if text in f"{c.name} {c.email}".lower()]
        self.table.set_items(shown, key=lambda c: c.id)
        self._count.configure(text=f"{len(shown)} of {len(self._customers)} customers · "
                                   "read-only")
