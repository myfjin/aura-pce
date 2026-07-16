"""stale_lock_detect: detect and clean up stale lock files.

Claim: a lock file older than a threshold is stale and can be safely removed.
Post-condition: a fresh lock is NOT stale; an old lock IS stale.
"""
import os, time

def is_stale(lock_path: str, max_age_sec: float = 300.0) -> bool:
    """Return True if lock file is older than max_age_sec."""
    if not os.path.exists(lock_path):
        return False
    age = time.time() - os.path.getmtime(lock_path)
    return age > max_age_sec

if __name__ == "__main__":
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        lock = os.path.join(d, "fresh.lock")
        # Fresh lock — not stale
        with open(lock, "w") as f:
            f.write("locked")
        assert not is_stale(lock, max_age_sec=3600), "fresh lock should not be stale"
        # Simulate old lock by setting mtime far in past
        old_time = time.time() - 7200
        os.utime(lock, (old_time, old_time))
        assert is_stale(lock, max_age_sec=3600), "old lock should be stale"
    print("PASS: stale lock detection verified")