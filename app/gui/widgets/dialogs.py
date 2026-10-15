"""Modal popups: messages, yes/no confirmation, and simple forms."""

import tkinter
from collections.abc import Callable
from dataclasses import dataclass, field

import customtkinter as ctk

from app.gui import theme
from app.gui.theme import COLORS, PAD_L, PAD_M, PAD_S


def make_modal(window, focus_widget=None) -> None:
    """Grab all input for `window`, so the user must close it before clicking anything
    else. Called a moment after the window opens: grab_set fails until it is visible."""
    if not window.winfo_exists():
        return
    try:
        window.grab_set()
    except tkinter.TclError:  # not viewable (e.g. the hidden window in tests): skip
        pass
    if focus_widget is not None:
        focus_widget.focus_set()


def center_on(window, parent) -> None:
    window.update_idletasks()
    x = parent.winfo_rootx() + (parent.winfo_width() - window.winfo_reqwidth()) // 2
    y = parent.winfo_rooty() + (parent.winfo_height() - window.winfo_reqheight()) // 3
    window.geometry(f"+{max(x, 0)}+{max(y, 0)}")


def _popup(window, parent, title: str) -> None:
    """Settings shared by every dialog."""
    window.title(title)
    window.configure(fg_color=COLORS["surface"])
    window.resizable(False, False)
    window.transient(parent)  # stays on top of the main window, no taskbar entry


def _accent_bar(frame, color: str) -> None:
    ctk.CTkFrame(frame, height=4, width=48, fg_color=color, corner_radius=2).pack(
        anchor="w", pady=(0, PAD_S))


class MessageDialog(ctk.CTkToplevel):
    """A small modal window: colour-coded title, message, OK button."""

    def __init__(self, parent, title: str, message: str, kind: str = "error") -> None:
        super().__init__(parent)
        _popup(self, parent, title)
        accent = {"error": COLORS["danger"], "warning": COLORS["warning"],
                  "info": COLORS["accent"], "success": COLORS["success"]}[kind]

        frame = ctk.CTkFrame(self, fg_color="transparent")
        frame.pack(padx=PAD_L, pady=PAD_L, fill="both", expand=True)
        _accent_bar(frame, accent)
        ctk.CTkLabel(frame, text=title, font=theme.heading_font(),
                     text_color=COLORS["text"], anchor="w").pack(fill="x")
        ctk.CTkLabel(frame, text=message, font=theme.body_font(),
                     text_color=COLORS["text_muted"], wraplength=380, justify="left",
                     anchor="w").pack(fill="x", pady=(PAD_S, PAD_M))
        ok = ctk.CTkButton(frame, text="OK", width=96, command=self.destroy,
                           **theme.primary_button_style())
        ok.pack(anchor="e")

        self.bind("<Return>", lambda _e: self.destroy())
        self.bind("<Escape>", lambda _e: self.destroy())
        center_on(self, parent)
        self.after(50, make_modal, self, ok)


def show_error(parent, title: str, message: str) -> MessageDialog:
    return MessageDialog(parent, title, message, kind="error")


def show_info(parent, title: str, message: str) -> MessageDialog:
    return MessageDialog(parent, title, message, kind="info")


class ConfirmDialog(ctk.CTkToplevel):
    """"Are you sure?" with Cancel and a confirm button. on_confirm() runs only when the
    confirm button is clicked; Cancel, Escape or closing the window do nothing."""

    def __init__(self, parent, title: str, message: str, on_confirm: Callable[[], None],
                 confirm_text: str = "Confirm", danger: bool = True) -> None:
        super().__init__(parent)
        _popup(self, parent, title)
        self._on_confirm = on_confirm

        frame = ctk.CTkFrame(self, fg_color="transparent")
        frame.pack(padx=PAD_L, pady=PAD_L, fill="both", expand=True)
        _accent_bar(frame, COLORS["danger"] if danger else COLORS["accent"])
        ctk.CTkLabel(frame, text=title, font=theme.heading_font(), text_color=COLORS["text"],
                     anchor="w").pack(fill="x")
        ctk.CTkLabel(frame, text=message, font=theme.body_font(),
                     text_color=COLORS["text_muted"], wraplength=380, justify="left",
                     anchor="w").pack(fill="x", pady=(PAD_S, PAD_M))
        buttons = ctk.CTkFrame(frame, fg_color="transparent")
        buttons.pack(fill="x")
        style = theme.primary_button_style()
        if danger:
            style.update(fg_color=COLORS["danger"], hover_color=COLORS["danger_hover"])
        ctk.CTkButton(buttons, text=confirm_text, command=self._confirm, **style).pack(
            side="right")
        cancel = ctk.CTkButton(buttons, text="Cancel", width=96, command=self.destroy,
                               **theme.secondary_button_style())
        cancel.pack(side="right", padx=PAD_S)

        self.bind("<Escape>", lambda _e: self.destroy())
        center_on(self, parent)
        # Focus starts on Cancel, so pressing Enter out of habit doesn't confirm.
        self.after(50, make_modal, self, cancel)

    def _confirm(self) -> None:
        self.destroy()
        self._on_confirm()


@dataclass
class Field:
    """One input in a FormDialog.
    kind: "entry" (one line), "text" (several lines) or "choice" (drop-down list)."""
    key: str
    label: str
    value: str = ""
    kind: str = "entry"
    choices: list[str] = field(default_factory=list)
    hint: str = ""  # small grey help text under the field


class FormDialog(ctk.CTkToplevel):
    """A modal form. Save calls on_submit(dialog, {key: text typed}).

    The dialog does NOT check the values: the service does, and raises a ValidationError
    with a clear message. The owner runs the service call, then either closes the
    dialog (dialog.destroy()) or calls dialog.failed() so the user can correct the input
    (what they typed stays in the form).
    """

    def __init__(self, parent, title: str, fields: list[Field],
                 on_submit: Callable[["FormDialog", dict], None],
                 submit_text: str = "Save", width: int = 440) -> None:
        super().__init__(parent)
        _popup(self, parent, title)
        self._on_submit = on_submit
        self._inputs: dict[str, object] = {}

        frame = ctk.CTkFrame(self, fg_color="transparent")
        frame.pack(padx=PAD_L, pady=PAD_L, fill="both", expand=True)
        ctk.CTkLabel(frame, text=title, font=theme.heading_font(), text_color=COLORS["text"],
                     anchor="w").pack(fill="x", pady=(0, PAD_M))
        for spec in fields:
            ctk.CTkLabel(frame, text=spec.label, font=theme.font(12, "bold"),
                         text_color=COLORS["text_muted"], anchor="w").pack(fill="x")
            widget = self._make_input(frame, spec, width)
            widget.pack(fill="x", pady=(2, 2 if spec.hint else PAD_S + 2))
            if spec.hint:
                ctk.CTkLabel(frame, text=spec.hint, font=theme.small_font(),
                             text_color=COLORS["text_muted"], anchor="w").pack(
                    fill="x", pady=(0, PAD_S))
            self._inputs[spec.key] = widget

        buttons = ctk.CTkFrame(frame, fg_color="transparent")
        buttons.pack(fill="x", pady=(PAD_S, 0))
        self.submit_button = ctk.CTkButton(buttons, text=submit_text, width=110,
                                           command=self.submit, **theme.primary_button_style())
        self.submit_button.pack(side="right")
        ctk.CTkButton(buttons, text="Cancel", width=96, command=self.destroy,
                      **theme.secondary_button_style()).pack(side="right", padx=PAD_S)

        self.bind("<Escape>", lambda _e: self.destroy())
        center_on(self, parent)
        first = next(iter(self._inputs.values()), None)
        self.after(50, make_modal, self, first)

    def _make_input(self, frame, spec: Field, width: int):
        if spec.kind == "choice":
            widget = ctk.CTkOptionMenu(
                frame, values=spec.choices or [""], width=width, height=38,
                font=theme.body_font(), fg_color=COLORS["bg"],
                button_color=COLORS["surface_hover"], button_hover_color=COLORS["border"],
                text_color=COLORS["text"], dropdown_fg_color=COLORS["surface"],
                dropdown_text_color=COLORS["text"], dropdown_font=theme.body_font())
            widget.set(spec.value or (spec.choices[0] if spec.choices else ""))
        elif spec.kind == "text":
            widget = ctk.CTkTextbox(frame, width=width, height=110, font=theme.body_font(),
                                    fg_color=COLORS["bg"], border_color=COLORS["border"],
                                    border_width=1, text_color=COLORS["text"], wrap="word")
            widget.insert("1.0", spec.value)
        else:
            widget = ctk.CTkEntry(frame, width=width, height=38, font=theme.body_font(),
                                  fg_color=COLORS["bg"], border_color=COLORS["border"],
                                  text_color=COLORS["text"])
            widget.insert(0, spec.value)
            widget.bind("<Return>", lambda _e: self.submit())
        return widget

    def values(self) -> dict[str, str]:
        result = {}
        for key, widget in self._inputs.items():
            if isinstance(widget, ctk.CTkTextbox):
                result[key] = widget.get("1.0", "end").strip()
            else:
                result[key] = widget.get()
        return result

    def set_value(self, key: str, text: str) -> None:
        """Fill in a field (used by tests)."""
        widget = self._inputs[key]
        if isinstance(widget, ctk.CTkTextbox):
            widget.delete("1.0", "end")
            widget.insert("1.0", text)
        elif isinstance(widget, ctk.CTkOptionMenu):
            widget.set(text)
        else:
            widget.delete(0, "end")
            widget.insert(0, text)

    def submit(self) -> None:
        if str(self.submit_button.cget("state")) == "disabled":
            return  # already saving (e.g. Enter pressed twice)
        self.submit_button.configure(state="disabled")
        self._on_submit(self, self.values())

    def failed(self) -> None:
        """Saving failed (the owner already showed why): let the user try again."""
        if self.winfo_exists():
            self.submit_button.configure(state="normal")
