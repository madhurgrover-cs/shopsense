"""Run slow work (database and AI calls) in a background thread.

Why: Tkinter draws the window on the MAIN thread. If a button handler waits 2 seconds
for Neon (or 30 s for the AI model), the window freezes ("Not responding") for that
long. So handlers hand the slow call to a worker thread and return immediately.

The catch: Tkinter widgets may ONLY be touched from the main thread. So we never call
the success/error callbacks from the worker. Instead the main thread checks every
40 ms (root.after) whether the work is finished, and then runs the callback itself.

Usage in a screen:

    self.app.tasks.run(
        catalog_service.browse_products, category_id,
        on_success=self.show_products,       # runs on the main thread with the result
        message="Loading products...",       # shown next to the spinner meanwhile
    )
"""

import itertools
import logging
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any

log = logging.getLogger(__name__)

POLL_MS = 40


class TaskRunner:
    def __init__(self, root, on_busy_change: Callable[[str | None], None],
                 on_error: Callable[[BaseException], None], max_workers: int = 2) -> None:
        """
        root           - the main window (used for root.after polling)
        on_busy_change - called with the newest active message, or None when idle
        on_error       - default error handler (shows a popup) when a task has none
        """
        self._root = root
        self._on_busy_change = on_busy_change
        self._default_on_error = on_error
        # Two workers: enough for e.g. "load cart" and "load recommendations" at once,
        # while keeping connections and memory low on a 4 GB laptop.
        self._executor = ThreadPoolExecutor(max_workers=max_workers,
                                            thread_name_prefix="shopsense-worker")
        self._ids = itertools.count()
        self._active: dict[int, str] = {}  # task id -> loading message
        self._closed = False

    @property
    def busy(self) -> bool:
        return bool(self._active)

    def run(self, func: Callable[..., Any], *args,
            on_success: Callable[[Any], None] | None = None,
            on_error: Callable[[BaseException], None] | None = None,
            message: str = "Loading...", **kwargs) -> Future | None:
        """Start func(*args, **kwargs) in the background. Returns its Future."""
        if self._closed:
            return None
        task_id = next(self._ids)
        self._active[task_id] = message
        self._notify()
        future = self._executor.submit(func, *args, **kwargs)
        self._root.after(POLL_MS, self._check, task_id, future, on_success, on_error)
        return future

    def _check(self, task_id: int, future: Future, on_success, on_error) -> None:
        """Runs on the MAIN thread, every POLL_MS, until the task has finished."""
        if self._closed:
            return
        if not future.done():
            self._root.after(POLL_MS, self._check, task_id, future, on_success, on_error)
            return

        del self._active[task_id]
        self._notify()
        error = future.exception()
        try:
            if error is not None:
                (on_error or self._default_on_error)(error)
            elif on_success is not None:
                on_success(future.result())
        except Exception as callback_error:  # a bug in a callback must not kill the loop
            log.exception("Error in task callback")
            self._default_on_error(callback_error)

    def _notify(self) -> None:
        # Show the most recently started task's message (the one the user just asked for).
        message = next(reversed(self._active.values())) if self._active else None
        self._on_busy_change(message)

    def shutdown(self) -> None:
        """Called when the window closes: drop queued work, don't wait for running work."""
        self._closed = True
        self._executor.shutdown(wait=False, cancel_futures=True)
