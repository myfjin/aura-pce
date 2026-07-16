"""disk_space_guard: check that available disk space is above a minimum threshold.

Claim: raises an error if free space on a given path falls below the required minimum.
Post-condition: a path with sufficient space passes; a path below threshold raises.
"""
import shutil

def guard_disk_space(path: str, min_gb: float = 1.0) -> None:
    """Raise RuntimeError if free space at path is below min_gb gigabytes."""
    free_bytes = shutil.disk_usage(path).free
    free_gb = free_bytes / (1024 ** 3)
    if free_gb < min_gb:
        raise RuntimeError(f"Low disk space: {free_gb:.2f} GB free, need {min_gb} GB")

if __name__ == "__main__":
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        # Should pass — temp dir has space
        guard_disk_space(d, min_gb=0.000001)
        # Should fail — impossible threshold
        try:
            guard_disk_space(d, min_gb=1e12)
            assert False, "should have raised"
        except RuntimeError:
            pass
    print("PASS: disk space guard verified")