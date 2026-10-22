"""matplotlib charts embedded in the window (FigureCanvasTkAgg), styled to match the app.

Memory notes (4 GB laptop):
- matplotlib is imported inside ChartCard, not at the top of this file. app.py imports
  every screen at startup, so a top-level import would load matplotlib (~30 MB) for
  customers too, who never see a chart.
- We use matplotlib.figure.Figure directly, NOT pyplot. pyplot keeps every figure in a
  global list until plt.close(); a plain Figure is freed with the widget that shows it.

Light / dark mode: matplotlib takes single colour strings, so painters look colours up
with theme.resolve() when they run. ChartCard keeps the last painter and simply runs it
again when the mode changes, so a chart is re-coloured without fetching its data again.
"""

from collections.abc import Callable, Sequence
from decimal import Decimal

import customtkinter as ctk

from app.gui import theme
from app.gui.theme import COLORS, PAD_L, PAD_M, PAD_S, resolve

CHART_COLORS = theme.CHART_COLORS  # Flipkart blue and orange first


def compact_inr(value: float) -> str:
    """Short rupee amounts for chart labels, Indian style: ₹950, ₹12.5k, ₹4.2L, ₹1.3Cr
    (1 lakh = 1,00,000; 1 crore = 1,00,00,000)."""
    value = float(value)
    for limit, suffix in ((1e7, "Cr"), (1e5, "L"), (1e3, "k")):
        if abs(value) >= limit:
            return f"₹{value / limit:.1f}{suffix}".replace(".0", "")
    return f"₹{value:.0f}"


class ChartCard(ctk.CTkFrame):
    """A card with a title and one matplotlib chart. Call draw(painter) with a function
    painter(figure) that draws on the figure; call it again to redraw with new data."""

    def __init__(self, parent, title: str, height: int = 260) -> None:
        super().__init__(parent, fg_color=COLORS["surface"], corner_radius=theme.CORNER_RADIUS,
                         border_width=1, border_color=COLORS["border"])
        from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
        from matplotlib.figure import Figure

        ctk.CTkLabel(self, text=title, font=theme.font(14, "bold"), text_color=COLORS["text"],
                     anchor="w").pack(fill="x", padx=PAD_L, pady=(PAD_M, 0))
        # matplotlib knows nothing about Windows display scaling: at 150 % its text would
        # look tiny next to the rest of the app. Raising the dpi by the same factor makes
        # chart text the same size as CTk text.
        scale = ctk.ScalingTracker.get_widget_scaling(self)
        self.figure = Figure(figsize=(5, height / 100), dpi=100 * scale,
                             layout="constrained")
        self.canvas = FigureCanvasTkAgg(self.figure, master=self)
        widget = self.canvas.get_tk_widget()
        widget.configure(highlightthickness=0, height=int(height * scale))
        widget.pack(fill="both", expand=True, padx=PAD_S, pady=(0, PAD_S))  # inside the border
        self._painter: Callable | None = None
        self._apply_background()

    def draw(self, painter: Callable) -> None:
        self._painter = painter
        self.figure.clear()
        painter(self.figure)
        self.canvas.draw_idle()

    def _apply_background(self) -> None:
        """The figure and the Tk canvas behind it are not CTk widgets: colour them by
        hand for the current mode."""
        surface = resolve(COLORS["surface"])
        self.figure.set_facecolor(surface)
        self.canvas.get_tk_widget().configure(background=surface)

    def _set_appearance_mode(self, mode_string: str) -> None:
        """Called by CustomTkinter when the light / dark mode changes (see table.py)."""
        super()._set_appearance_mode(mode_string)
        self._apply_background()
        if self._painter is not None:
            self.draw(self._painter)  # same data, new colours
        else:
            self.canvas.draw_idle()

    def destroy(self) -> None:
        self.figure.clear()  # drop the drawing data right away, not at garbage collection
        super().destroy()


def _style(ax) -> None:
    ax.set_facecolor(resolve(COLORS["surface"]))
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(resolve(COLORS["border"]))
    ax.tick_params(colors=resolve(COLORS["text_muted"]), labelsize=8)
    ax.grid(color=resolve(COLORS["border"]), linewidth=0.6)
    ax.set_axisbelow(True)


def _money_axis(axis) -> None:
    from matplotlib.ticker import FuncFormatter
    axis.set_major_formatter(FuncFormatter(lambda v, _pos: compact_inr(v)))


def revenue_trend(days: Sequence, revenue: Sequence[Decimal]) -> Callable:
    """Line chart of revenue per day (days = dates, oldest first)."""
    def paint(figure) -> None:
        ax = figure.add_subplot()
        _style(ax)
        x = list(range(len(days)))
        y = [float(v) for v in revenue]
        accent = resolve(COLORS["accent"])
        ax.plot(x, y, color=accent, linewidth=2, marker="o", markersize=3)
        ax.fill_between(x, y, color=accent, alpha=0.08)  # flat light fill
        step = max(1, len(days) // 6)  # about 6 date labels, so they don't overlap
        ax.set_xticks(x[::step], [d.strftime("%d %b") for d in days[::step]])
        ax.set_ylim(bottom=0)
        ax.grid(axis="x", visible=False)
        _money_axis(ax.yaxis)
    return paint


def horizontal_bars(labels: Sequence[str], values: Sequence[Decimal],
                    max_label: int = 26) -> Callable:
    """Bar chart, biggest at the top, each bar labelled with its amount."""
    def paint(figure) -> None:
        ax = figure.add_subplot()
        _style(ax)
        names = [n if len(n) <= max_label else n[:max_label - 1] + "…" for n in labels]
        amounts = [float(v) for v in values]
        y = list(range(len(names)))[::-1]  # first item at the top
        colors = [CHART_COLORS[i % len(CHART_COLORS)] for i in range(len(names))]
        bars = ax.barh(y, amounts, color=colors, height=0.6)
        ax.set_yticks(y, names)
        ax.bar_label(bars, labels=[compact_inr(a) for a in amounts], padding=4,
                     color=resolve(COLORS["text_muted"]), fontsize=8)
        ax.set_xlim(right=max(amounts, default=1) * 1.18)  # room for the labels
        ax.grid(axis="y", visible=False)
        _money_axis(ax.xaxis)
    return paint
