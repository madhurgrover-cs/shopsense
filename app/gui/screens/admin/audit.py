"""Admin: the audit log, newest first: who changed what, and when.

Entries are written by the services themselves (audit_service.record_admin_action), in
the same transaction as the change, so this list can't miss or invent a change."""

from app.gui import formatting as fmt
from app.gui.screens.admin.common import button, dropdown, toolbar
from app.gui.screens.base import Screen
from app.gui.theme import PAD_L, PAD_S, PAD_XL
from app.gui.widgets.common import muted
from app.gui.widgets.table import Column, DataTable
from app.services import audit_service
from app.services.dto import AuditEntry

LIMIT = 300
ALL = "Everything"
ENTITIES = {"Products": "product", "Stock": "stock", "Orders": "order", "Coupons": "coupon"}


class AuditLogScreen(Screen):
    title = "Audit log"

    def __init__(self, parent, app) -> None:
        super().__init__(parent, app)
        self._entries: list[AuditEntry] = []
        bar = toolbar(self)
        self._entity = dropdown(bar, [ALL, *ENTITIES], lambda _v: self._filter(), width=150)
        self._entity.pack(side="left")
        self._count = muted(bar, "")
        self._count.pack(side="left", padx=PAD_S + 4)
        button(bar, "Refresh", self.on_show, width=100).pack(side="right")

        self.table = DataTable(self, [
            Column("When", 170, lambda e: fmt.when(e.created_at), sort=lambda e: e.created_at),
            Column("Admin", 140, lambda e: e.user_name or "(deleted user)"),
            Column("Action", 110, lambda e: e.action.replace("_", " ")),
            Column("What", 90, lambda e: e.entity),
            Column("ID", 60, lambda e: e.entity_id, sort=lambda e: e.entity_id, anchor="e"),
            Column("Details", 420, lambda e: e.details or ""),
        ], empty_text="No admin actions recorded yet.")
        self.table.pack(fill="both", expand=True, padx=PAD_XL, pady=(0, PAD_L))

    def on_show(self, **kwargs) -> None:
        self.app.tasks.run(audit_service.list_recent, self.app.user, LIMIT,
                           on_success=self._loaded, message="Loading audit log...")

    def _loaded(self, entries: list[AuditEntry]) -> None:
        self._entries = entries
        self._filter()

    def _filter(self) -> None:
        entity = ENTITIES.get(self._entity.get())
        shown = [e for e in self._entries if entity is None or e.entity == entity]
        self.table.set_items(shown, key=lambda e: e.id)
        self._count.configure(text=f"{len(shown)} entries (latest {LIMIT} actions)")
