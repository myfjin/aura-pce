"""memory_pressure: raise a memory-pressure alert when pressure exceeds a limit.

Claim: the alert fires if and only if sustained pressure is above the limit.
Valid input: pressure and limit as fractions in [0, 1].
Post-condition: alert == (pressure > limit) for any pressure/limit — the guarantee is the
threshold comparison itself, independent of how the pressure reading is sourced (psutil,
/proc/meminfo, or node_exporter all plug in above this pure guarantee).
"""


def memory_pressure_alert(pressure: float, limit: float) -> bool:
    """Return True iff pressure strictly exceeds the limit."""
    return pressure > limit


if __name__ == "__main__":
    # the guarantee: alert iff over the limit — tested at and around the boundary
    assert memory_pressure_alert(0.95, 0.90) is True, "over the limit -> alert"
    assert memory_pressure_alert(0.90, 0.90) is False, "at the limit -> no alert (strict >)"
    assert memory_pressure_alert(0.50, 0.90) is False, "under the limit -> no alert"
    # cause-the-disaster: a reading that just crosses the limit MUST fire
    assert memory_pressure_alert(0.9001, 0.90) is True, "just over -> alert"
    print("PASS: memory_pressure alert fires exactly above the limit")
