# V2 schema-3 Clean Install TLSFIX5 candidate, 2026-11-20

Production DNS resolves only to 100.111.221.74; installer production target pins this IPv4 address. INPUTFIX3 also reads absent optional transcription policy without a StrictMode exception.

Caddy runs from caddy/bin, where its service SID already has Read and Execute. Caddy uses a separately issued trusted pair in a TLS directory with a direct RX ACE and read-only file ACEs. No key or certificate is part of this ZIP.

Status: local verification only for TLSFIX5. Server execution authorized by Commander 5 on 2026-11-20. Production HTTPS remains unverified.

Deploy SHA256: `d7c523a167eec578a03ed9b0ede62868aed1d4c59f50fbf2b78f997fbb79a5db`

Tools SHA256: `abce6a9ce7afde4ab938d2d66062abf732668960c8c12b53fdd2e9d9b68fbaba`

Backend Python 3.13.14 full pytest: 364 PASS, 1 deprecation warning. Frontend: 38/38 tests, build, final 8/8 synthetic E2E PASS (first run 7/8 timeout preserved in evidence note).

Installer: 15 local suites passed, including 21 rehearsal cases. Mutation cases were not rerun for this candidate. Required Windows runtime tests remain NOT RUN.

Role-change feature is a separate candidate pending independent acceptance; it is not in this deploy ZIP.

Next candidate (hardening, not part of this TLSFIX5 ZIP): see RELEASE_NOTES_V2_HARDENING.md and docs/UPGRADE_IN_PLACE.md.
