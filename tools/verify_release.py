import hashlib
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "SHA256SUMS.txt"


def verify():
    if not MANIFEST.is_file():
        raise RuntimeError("MISSING_SHA256_MANIFEST")
    seen = set()
    failures = []
    for line in MANIFEST.read_text(encoding="utf-8").splitlines():
        if "  " not in line:
            failures.append("MALFORMED_MANIFEST_LINE")
            continue
        expected, relative = line.split("  ", 1)
        if not re.fullmatch(r"[0-9a-f]{64}", expected):
            failures.append("INVALID_DIGEST")
            continue
        path = Path(relative)
        if path.is_absolute() or ".." in path.parts or relative in seen:
            failures.append("UNSAFE_OR_DUPLICATE_PATH")
            continue
        seen.add(relative)
        full = ROOT / path
        if not full.is_file():
            failures.append("MISSING:" + relative)
            continue
        actual = hashlib.sha256(full.read_bytes()).hexdigest()
        if actual != expected:
            failures.append("MISMATCH:" + relative)
    print(f"Manifest entries: {len(seen)}")
    print(f"Failures: {len(failures)}")
    for issue in failures:
        print(issue)
    return not failures


if __name__ == "__main__":
    raise SystemExit(0 if verify() else 1)
