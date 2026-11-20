# WinSW/Caddy provenance, 2026-11-20

Здійснено окреме HTTPS-завантаження з офіційних GitHub release assets та порівняння байтів із tools ZIP цього кандидата. Це локальне підтвердження походження конкретних байтів із release asset; Authenticode підпису в EXE немає.

| Tool | Офіційний release asset | SHA256 завантаженого asset | SHA256 вкладеного EXE | Порівняння з tools ZIP |
| --- | --- | --- | --- | --- |
| WinSW 2.12.0 x64 | [WinSW-x64.exe](https://github.com/winsw/winsw/releases/download/v2.12.0/WinSW-x64.exe) | `05b82d46ad331cc16bdc00de5c6332c1ef818df8ceefcd49c726553209b3a0da` | той самий | байти однакові |
| Caddy 2.11.9 Windows amd64 | [caddy_2.11.9_windows_amd64.zip](https://github.com/caddyserver/caddy/releases/download/v2.11.9/caddy_2.11.9_windows_amd64.zip) | `ad93112d335ee687100c4c9f11bced16ca590377976b7fe7883882b9e797e472` | `2622e239c79df700b0eb92cbd950d1edee365e155a7859f358f0e55f002df591` | байти `caddy.exe` однакові |

Офіційні сторінки релізів: [WinSW v2.12.0](https://github.com/winsw/winsw/releases/tag/v2.12.0), [Caddy v2.11.9](https://github.com/caddyserver/caddy/releases/tag/v2.11.9). Для Caddy ZIP CRC/розпакування пройшли; `caddy.exe` має 52,010,496 байтів. Для WinSW EXE — 18,243,033 байти. `Get-AuthenticodeSignature` для обох: `NotSigned`.

Локальні копії завантажених asset зберігаються поза immutable release package в `installer-integration/tool-provenance-local/`. Перед використанням на VM рекомендовано повторити SHA256 tools ZIP й перевірити політику виконання непідписаних EXE цільового середовища.
