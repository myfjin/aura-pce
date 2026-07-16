"""atomic_write_temp_rename: write to a temp file, then atomically rename into place.

Claim: a file write that completes without corruption even if interrupted mid-write.
Post-condition: after the atomic rename, the target file contains exactly the intended content.
Failure scenario: a crash during a direct write leaves a partial file; atomic rename avoids this.
"""
import os, tempfile

def atomic_write(path: str, content: str) -> None:
    """Write content to path atomically via temp + rename."""
    dirpath = os.path.dirname(path) or "."
    with tempfile.NamedTemporaryFile(mode="w", dir=dirpath, delete=False) as f:
        tmp = f.name
        f.write(content)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)

if __name__ == "__main__":
    import tempfile, os
    with tempfile.TemporaryDirectory() as d:
        target = os.path.join(d, "out.txt")
        atomic_write(target, "hello atomic")
        with open(target) as f:
            assert f.read() == "hello atomic", "content mismatch after atomic write"
        print("PASS: atomic write verified")