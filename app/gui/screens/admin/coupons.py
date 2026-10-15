"""Admin coupons: list, create and deactivate (coupon_service, audited)."""

from datetime import timedelta

from app.gui import formatting as fmt
from app.gui.screens.admin.common import button, set_enabled, toolbar
from app.gui.screens.base import Screen
from app.gui.theme import PAD_L, PAD_S, PAD_XL
from app.gui.widgets.common import muted
from app.gui.widgets.dialogs import Field, FormDialog
from app.gui.widgets.table import Column, DataTable
from app.services import coupon_service
from app.services.dto import CouponInfo
from app.services.validation import today


def coupon_state(coupon: CouponInfo) -> str:
    if not coupon.is_active:
        return "Deactivated"
    if coupon.valid_until <= fmt.now():
        return "Expired"
    return "Active"


class CouponsScreen(Screen):
    title = "Coupons"

    def __init__(self, parent, app) -> None:
        super().__init__(parent, app)
        bar = toolbar(self)
        self._count = muted(bar, "")
        self._count.pack(side="left")
        button(bar, "+ New coupon", self._create, kind="primary", width=140).pack(side="right")
        self._deactivate = button(bar, "Deactivate", self._deactivate_selected, kind="danger")
        self._deactivate.pack(side="right", padx=PAD_S)

        self.table = DataTable(self, [
            Column("Code", 180, lambda c: c.code),
            Column("Discount", 100, lambda c: f"{c.percent_off}%", sort=lambda c: c.percent_off,
                   anchor="e"),
            Column("Valid until", 200, lambda c: fmt.when(c.valid_until),
                   sort=lambda c: c.valid_until),
            Column("Status", 140, coupon_state),
        ], on_select=lambda _c: self._update_buttons(),
            row_color=lambda c: None if coupon_state(c) == "Active" else "text_muted",
            empty_text="No coupons yet.")
        self.table.pack(fill="both", expand=True, padx=PAD_XL, pady=(0, PAD_L))
        self._update_buttons()

    def on_show(self, **kwargs) -> None:
        self._reload()

    def _reload(self, select: str | None = None) -> None:
        def loaded(coupons: list[CouponInfo]) -> None:
            self.table.set_items(coupons, key=lambda c: c.code)
            active = sum(coupon_state(c) == "Active" for c in coupons)
            self._count.configure(text=f"{len(coupons)} coupons · {active} usable now")
            if select:
                self.table.select(select)
            self._update_buttons()
        self.app.tasks.run(coupon_service.list_coupons, self.app.user, on_success=loaded,
                           message="Loading coupons...")

    def _update_buttons(self) -> None:
        coupon = self.table.selected
        set_enabled(self._deactivate, coupon is not None and coupon.is_active)

    def _create(self) -> None:
        def save(dialog: FormDialog, values: dict) -> None:
            def saved(coupon: CouponInfo) -> None:
                dialog.destroy()
                self.app.show_message("Coupon created",
                                      f"{coupon.code} gives {coupon.percent_off}% off until "
                                      f"{fmt.day(coupon.valid_until)}.", kind="success")
                self._reload(select=coupon.code)

            def failed(error) -> None:
                self.app.show_error(error)
                dialog.failed()

            self.app.tasks.run(coupon_service.create_coupon, self.app.user, values["code"],
                               values["percent_off"], values["valid_until"],
                               on_success=saved, on_error=failed, message="Creating coupon...")

        FormDialog(self.app, "New coupon", [
            Field("code", "Code", hint="3-30 letters or digits, e.g. SUMMER20"),
            Field("percent_off", "Discount (%)", "10", hint="Whole number from 1 to 90"),
            Field("valid_until", "Valid until", (today() + timedelta(days=30)).isoformat(),
                  hint="YYYY-MM-DD. The coupon works until the end of that day."),
        ], save, submit_text="Create")

    def _deactivate_selected(self) -> None:
        coupon = self.table.selected
        if coupon is None or not coupon.is_active:
            return

        def deactivate() -> None:
            self.app.tasks.run(coupon_service.deactivate_coupon, self.app.user, coupon.code,
                               on_success=lambda c: self._reload(select=c.code),
                               message="Deactivating coupon...")

        self.app.confirm(f"Deactivate {coupon.code}?",
                         "Customers will no longer be able to use this coupon. Orders that "
                         "already used it keep their discount.",
                         deactivate, confirm_text="Deactivate")
