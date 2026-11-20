# Interactive console input correction (2026-11-20)

Target: `DESKTOP-JTGC2SG`. The first interactive launcher failed to parse because its UTF-8 text had no BOM; an ASCII-only operator launcher replaced it. The installer then stopped before creating `C:\srv` because `EnableTranscripting` was absent in the local policy registry key and a property read under StrictMode threw.

The installer now invokes the Python child directly from the same PowerShell console and checks the returned `$LASTEXITCODE`. This lets Python `getpass` read the actual console input rather than the truncated input observed when PowerShell `Start-Process -NoNewWindow` was used.

The server input diagnostic using `Start-Process -NoNewWindow` returned length 1 for each test input, even though the same input was repeated. A direct invocation diagnostic was opened and awaits a disposable input check. The installer change was followed by the local suite run, which passed 15/15 suites including 21 rehearsal cases.

The diagnostic did not use SMTP credentials, start services, or create databases. The full server runtime gate remains unverified until an actual interactive installation.
