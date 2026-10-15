"""Admin: reviews flagged as negative by sentiment analysis (VADER score below -0.3).
Selecting a review shows its full text underneath the table."""

from app.gui import formatting as fmt
from app.gui.screens.admin.common import button, toolbar
from app.gui.screens.base import Screen
from app.gui.theme import COLORS, PAD_L, PAD_M, PAD_XL
from app.gui.widgets.common import auto_wrap, card, label, muted
from app.gui.widgets.table import Column, DataTable
from app.services import review_service
from app.services.dto import ReviewInfo


class FlaggedReviewsScreen(Screen):
    title = "Flagged reviews"

    def __init__(self, parent, app) -> None:
        super().__init__(parent, app)
        bar = toolbar(self)
        self._count = muted(bar, "")
        self._count.pack(side="left")
        button(bar, "Refresh", self.on_show, width=100).pack(side="right")

        self.table = DataTable(self, [
            Column("Score", 70, lambda r: f"{r.sentiment_score:+.2f}",
                   sort=lambda r: r.sentiment_score, anchor="e"),
            Column("Rating", 90, lambda r: fmt.stars(r.rating), sort=lambda r: r.rating),
            Column("Product", 260, lambda r: r.product_name),
            Column("Customer", 150, lambda r: r.user_name),
            Column("Date", 110, lambda r: fmt.day(r.created_at), sort=lambda r: r.created_at),
            Column("Review", 380, lambda r: (r.comment or "").replace("\n", " ")),
        ], on_select=self._show_review, empty_text="No flagged reviews.")
        self.table.pack(fill="both", expand=True, padx=PAD_XL, pady=(0, PAD_M))

        self._detail = card(self)
        self._detail.pack(fill="x", padx=PAD_XL, pady=(0, PAD_L))
        self._detail_title = label(self._detail, "Select a review to read all of it.",
                                   size=14, weight="bold")
        self._detail_title.pack(fill="x", padx=PAD_L, pady=(PAD_M, 2))
        self._detail_text = label(self._detail, "", size=13, color=COLORS["text_muted"],
                                  wraplength=600)
        self._detail_text.pack(fill="x", padx=PAD_L, pady=(0, PAD_M))
        auto_wrap(self._detail_text, self._detail, padding=2 * PAD_L)

    def on_show(self, **kwargs) -> None:
        self.app.tasks.run(review_service.list_flagged_reviews, self.app.user,
                           on_success=self._loaded, message="Loading flagged reviews...")

    def _loaded(self, reviews: list[ReviewInfo]) -> None:
        self.table.set_items(reviews, key=lambda r: r.id)
        self._count.configure(
            text=f"{len(reviews)} reviews with a sentiment score below -0.3, most negative "
                 "first")

    def _show_review(self, review: ReviewInfo) -> None:
        self._detail_title.configure(
            text=f"{review.product_name}  ·  {fmt.stars(review.rating)}  ·  "
                 f"score {review.sentiment_score:+.2f}  ·  {review.user_name}, "
                 f"{fmt.day(review.created_at)}")
        self._detail_text.configure(text=review.comment or "(no text)")

