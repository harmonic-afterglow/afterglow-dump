import threading

from afterglow_dump import concord


def test_every_library_call_runs_on_one_thread_that_stays():
    # hidapi ties its macOS device manager to the thread that initialised it.
    seen = []

    def call():
        seen.append(threading.get_ident())
        return len(seen)

    for _ in range(3):
        worker = threading.Thread(target=lambda: concord._LibraryThread.call(call))
        worker.start()
        worker.join()
    assert len(set(seen)) == 1 and seen[0] != threading.get_ident()
    [thread] = [t for t in threading.enumerate() if t.name == concord._LibraryThread.NAME]
    assert thread.daemon
