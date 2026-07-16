"""zscore_anomaly: flag a reading anomalous exactly when its |z-score| exceeds a threshold.

Claim: points whose absolute z-score exceeds the threshold are flagged; points near the mean are not.
Valid input: a list of >= 2 numeric readings.
Post-condition: index i is flagged iff |(data[i] - mean) / stdev| > threshold.
"""
import statistics


def zscore_anomalies(data: list, threshold: float = 2.0) -> list:
    """Return indices of points with |z-score| > threshold."""
    if len(data) < 2:
        return []
    mu = statistics.mean(data)
    sd = statistics.stdev(data)
    if sd == 0:
        return []
    return [i for i, x in enumerate(data) if abs((x - mu) / sd) > threshold]


if __name__ == "__main__":
    # uniform data -> no anomalies (sd == 0 guard)
    assert zscore_anomalies([10, 10, 10, 10, 10]) == [], "uniform data -> no anomalies"
    # a stable baseline with one clear outlier -> only the outlier is flagged.
    # (A single outlier in a *tiny* sample inflates the stdev and hides itself; a real
    #  baseline is needed for the z-score to actually exceed 2 — that subtlety is the point.)
    baseline = [10, 11, 9, 10, 12, 8, 10, 11, 9, 10, 10, 12, 8, 11, 9, 10, 10, 11, 9, 10]
    data = baseline + [100]
    flagged = zscore_anomalies(data)
    assert flagged == [len(data) - 1], f"only the outlier (100) should be flagged, got {flagged}"
    # false-positive guard: a normal reading near the mean is NOT flagged
    assert zscore_anomalies(baseline + [10]) == [], "a normal point -> not flagged"
    print("PASS: z-score flags the outlier and only the outlier")
