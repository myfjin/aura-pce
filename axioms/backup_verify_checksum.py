"""backup_verify_checksum: compute and verify a checksum to detect backup corruption.

Claim: a file's checksum computed before backup matches the checksum computed after restore.
Post-condition: identical files produce identical checksums; a single-bit flip is detected.
"""
import hashlib

def checksum(path: str) -> str:
    """Return SHA-256 hex digest of file at path."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()

if __name__ == "__main__":
    import tempfile, os
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "original.txt")
        dst = os.path.join(d, "restored.txt")
        with open(src, "w") as f:
            f.write("backup me")
        # Copy and checksum both
        with open(src, "rb") as f:
            with open(dst, "wb") as g:
                g.write(f.read())
        assert checksum(src) == checksum(dst), "checksums should match after copy"
        # Corrupt the copy
        with open(dst, "a") as f:
            f.write("x")
        assert checksum(src) != checksum(dst), "checksums should differ after corruption"
    print("PASS: backup checksum verification verified")