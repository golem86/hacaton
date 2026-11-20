"""Fail when synthetic questionnaire E2E sources or routes enter runtime images."""
from __future__ import annotations

import sys
import tarfile
from pathlib import Path


FORBIDDEN = (
    b"official_e2e_server",
    b"official-integration-harness",
    b"prototype-test-api",
    b"/_e2e/verify",
    b"e2e-only-form1",
    b"e2e-only-form2",
)


def check(archive_path: Path, label: str, forbidden_paths: tuple[str, ...]) -> None:
    with tarfile.open(archive_path, "r:") as archive:
        members = archive.getmembers()
        paths = [member.name.replace("\\", "/") for member in members]
        bad_paths = [path for path in paths if any(marker in path for marker in forbidden_paths)]
        if bad_paths:
            raise SystemExit(f"{label}: forbidden runtime image paths: {bad_paths[:5]}")
        for member in members:
            if not member.isfile() or member.size > 32 * 1024 * 1024:
                continue
            stream = archive.extractfile(member)
            if not stream:
                continue
            content = stream.read()
            found = [marker.decode("ascii") for marker in FORBIDDEN if marker in content]
            if found:
                raise SystemExit(f"{label}: forbidden markers {found} in {member.name}")
    print(f"{label} runtime image isolation PASS")


if len(sys.argv) != 3:
    raise SystemExit("usage: check-production-images.py BACKEND_IMAGE.tar FRONTEND_IMAGE.tar")

check(Path(sys.argv[1]), "backend", ("/prototypes/", "official_e2e_server.py"))
check(Path(sys.argv[2]), "frontend", ("official-integration-harness",))
