"""Tests for the background TaskRunner (no database needed).

A hidden Tk window provides the event loop; pump() processes events like mainloop()
would, until a condition is met.
"""

import threading
import time

import pytest

from app.exceptions import OutOfStockError
from app.gui.tasks import TaskRunner


@pytest.fixture
def root(gui_app):
    """Any Tk window can drive a TaskRunner; we reuse the one shared session window
    (see conftest.gui_app for why tests never create their own)."""
    return gui_app


def pump(root, until, timeout=5.0) -> int:
    """Process Tk events until until() is true. Returns how many loop turns it took."""
    turns, deadline = 0, time.time() + timeout
    while not until():
        assert time.time() < deadline, "timed out waiting for the task"
        root.update()
        time.sleep(0.005)
        turns += 1
    return turns


@pytest.fixture
def runner(root):
    events = {"busy": [], "errors": []}
    runner = TaskRunner(root, on_busy_change=events["busy"].append,
                        on_error=events["errors"].append)
    runner.events = events
    yield runner
    runner.shutdown()


def test_success_callback_runs_on_main_thread_with_result(root, runner):
    seen = {}

    def work(a, b, scale=1):
        seen["worker"] = threading.current_thread()
        return (a + b) * scale

    def done(result):
        seen["result"], seen["callback"] = result, threading.current_thread()

    runner.run(work, 2, 3, scale=10, on_success=done, message="Adding...")
    pump(root, lambda: "result" in seen)

    assert seen["result"] == 50
    assert seen["worker"] is not threading.main_thread()   # work ran in the background
    assert seen["callback"] is threading.main_thread()     # callback safe for Tk widgets
    assert runner.events["busy"] == ["Adding...", None]
    assert not runner.busy


def test_error_goes_to_task_handler_on_main_thread(root, runner):
    caught = []

    def fails():
        raise OutOfStockError("Test Phone", 0)

    runner.run(fails, on_error=lambda e: caught.append((e, threading.current_thread())))
    pump(root, lambda: caught)
    error, thread = caught[0]
    assert isinstance(error, OutOfStockError) and thread is threading.main_thread()
    assert runner.events["errors"] == []  # the task's own handler took it


def test_error_without_handler_uses_default_popup_handler(root, runner):
    runner.run(lambda: 1 / 0)
    pump(root, lambda: runner.events["errors"])
    assert isinstance(runner.events["errors"][0], ZeroDivisionError)


def test_bug_in_success_callback_is_reported_not_swallowed(root, runner):
    def broken_callback(_result):
        raise KeyError("oops")

    runner.run(lambda: 1, on_success=broken_callback)
    pump(root, lambda: runner.events["errors"])
    assert isinstance(runner.events["errors"][0], KeyError)


def test_window_stays_responsive_during_slow_task(root, runner):
    done = []
    runner.run(time.sleep, 0.5, on_success=done.append)
    turns = pump(root, lambda: done)
    # If the work blocked the main thread, the loop could only turn a few times.
    assert turns > 20


def test_newest_message_is_shown_while_several_tasks_run(root, runner):
    release = threading.Event()
    finished = []
    runner.run(release.wait, 5, on_success=finished.append, message="Loading cart...")
    runner.run(release.wait, 5, on_success=finished.append, message="Loading AI model...")
    assert runner.events["busy"][-1] == "Loading AI model..."
    release.set()
    pump(root, lambda: len(finished) == 2)
    assert runner.events["busy"][-1] is None


def test_no_callbacks_after_shutdown(root, runner):
    called = []
    release = threading.Event()
    runner.run(release.wait, 5, on_success=called.append)
    runner.shutdown()
    release.set()
    time.sleep(0.1)
    for _ in range(20):
        root.update()
        time.sleep(0.005)
    assert called == []
    assert runner.run(lambda: 1) is None  # new work is refused after shutdown
