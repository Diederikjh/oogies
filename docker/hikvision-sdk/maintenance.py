"""Application maintenance independent of any one feature's viewer leases."""


def maintenance_tick(live, playback):
    live.maintain()
    playback.reap()


def run_maintenance(live, playback, stop):
    while not stop.is_set():
        maintenance_tick(live, playback)
        stop.wait(1)
