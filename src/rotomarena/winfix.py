"""A fix for asyncio on Windows that kept killing every connection to Showdown at once.

When a connection closes while a read on it is pending, Windows aborts the read (WinError 995). asyncio's proactor
loop checks that the read's future isn't done, runs the completion callback, and when the callback raises, records
the error on the future: but the future can be finished or cancelled in between, and recording then raises
InvalidStateError out of the loop. poke-env runs every player's websocket on one background loop, so that one error
ended the thread and left all players waiting for messages that never came (9 and 10 Oct; the stall guard caught it
20 minutes later). A future that is already done has nobody left to tell, so the late report is dropped."""

import sys


def apply() -> None:
    if sys.platform != "win32":
        return
    from asyncio import windows_events

    future = windows_events._OverlappedFuture
    if getattr(future, "_rotomarena_fixed", False):
        return
    set_exception, set_result = future.set_exception, future.set_result

    def guarded_set_exception(self, exception):
        if not self.done():
            set_exception(self, exception)

    def guarded_set_result(self, result):
        if not self.done():
            set_result(self, result)

    future.set_exception, future.set_result = guarded_set_exception, guarded_set_result
    future._rotomarena_fixed = True
