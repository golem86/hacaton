# CI-02 — release-артефакти V2 і походження бінарників

| | |
| --- | --- |
| Для | №5; незалежна перевірка — №4 |
| Підготував | №2, 19.11.2026 |
| Підстава | наказ №5 «TARGETED FIX CI-01 / CI-02», завдання №2 |
| Дозвіл на завантаження | користувач №2, 19.11.2026: офіційні файли Caddy 2.11.9 і WinSW 2.12.0 з GitHub, лише хешування, без запуску |

## 1. Фактичні артефакти (`artifacts/`, атрибут «лише читання»)

| Файл | Розмір, B | SHA256 |
| --- | --- | --- |
| `integrity-v2-dde86e6-deploy.zip` | 12 741 254 | `62363714278da539db295bc809bd29bf0cc9bbde073ca8a26ff65f5211052559` |
| `integrity-v2-tools-winsw2.12.0-caddy2.11.9.zip` | 25 824 888 | `abce6a9ce7afde4ab938d2d66062abf732668960c8c12b53fdd2e9d9b68fbaba` |

Обидва файли передано **фізично**, а не лише записаними хешами.

Tools ZIP створено функцією installer-а `New-V2ToolsArtifact`, перевірено `Expand-V2Tools`: **PASS** (рівно 2 записи, SHA256 обох = закріплені еталони). Вміст:

| Запис | SHA256 | Джерело |
| --- | --- | --- |
| `winsw/integrity-v2-winsw.exe` | `05b82d46ad331cc16bdc00de5c6332c1ef818df8ceefcd49c726553209b3a0da` | `WinSW-x64.exe` з офіційного релізу v2.12.0 |
| `caddy/caddy.exe` | `2622e239c79df700b0eb92cbd950d1edee365e155a7859f358f0e55f002df591` | `caddy.exe` з офіційного `caddy_2.11.9_windows_amd64.zip` |

## 2. Походження бінарників (`download/` — оригінальні файли, без змін)

### WinSW 2.12.0

- **Джерело:** `https://github.com/winsw/winsw/releases/download/v2.12.0/` (реліз опубліковано 28.01.2023).
- **Офіційних контрольних сум WinSW не публікує** (у GitHub API в жодного файлу немає digest). Тому завантажено всі чотири Windows-варіанти й порівняно з еталоном:

| Файл релізу | Розмір, B | SHA256 | = еталон `05b82d46…`? |
| --- | --- | --- | --- |
| `WinSW-x64.exe` | 18 243 033 | `05b82d46ad331cc16bdc00de5c6332c1ef818df8ceefcd49c726553209b3a0da` | **так** |
| `WinSW.NET461.exe` | 655 872 | `b5066b7b…fc4f` | ні |
| `WinSW.NET4.exe` | 852 480 | `923111c7…cb66` | ні |
| `WinSW.NET2.exe` | 860 672 | `136ee80e…4812` | ні |

- **Метадані** `WinSW-x64.exe`: FileVersion 2.12.0.0; ProductVersion `2.12.0+eef5bade59fca0254e387ac73ed7625ba6aa7147`; CloudBees, Inc. **Підпису Authenticode немає.**
- **Висновок:** еталон, раніше зафіксований №4 з файлу V1 (`HacatonBackend.exe`), побайтно збігається з офіційним `WinSW-x64.exe` 2.12.0. Тепер джерело — офіційний реліз; **V1 як джерело не використовується.**

### Caddy 2.11.9

- **Джерело:** `https://github.com/caddyserver/caddy/releases/download/v2.11.9/` (реліз 05.11.2026).
- **Архів** `caddy_2.11.9_windows_amd64.zip`, 18 384 117 B:
  - SHA256 `ad93112d335ee687100c4c9f11bced16ca590377976b7fe7883882b9e797e472` = digest, який публікує GitHub;
  - SHA512 `98753d5d…6871` = рядок в офіційному `caddy_2.11.9_checksums.txt`.
- **`caddy_2.11.9_checksums.txt`:** SHA256 `e4e1e43b…299f` = digest GitHub. Підпис `.sig`/`.pem` (sigstore) **не перевірявся**: cosign на ПК №2 відсутній.
- **`caddy.exe`** з архіву: 52 010 496 B, SHA256 `2622e239…f591` = закріплений еталон. Підпису Authenticode немає (офіційні збірки Caddy не підписуються).

## 3. Deploy ZIP — походження з коміту `dde86e6`

- **Вміст:** 9 файлів. `SHA256SUMS.txt` усередині збігається з фактичними хешами вкладених файлів (перевіряє `clean-install.ps1` на етапі 4.2).
- **`integrity-v2-dde86e6-backend-src.zip`:** 52 файли, **52/52 побайтно = blob-и коміту `dde86e68f4405c23ec4aad14db80f0b764fb4556`** (`git hash-object --no-filters` проти `dde86e6:<шлях>`). Зайвих файлів немає; у коміті рівно 52 файли `backend/`. Git не змінювався, лише читання.
- **`integrity-v2-dde86e6-dist.zip`** (зібраний frontend) і **`wheelhouse-cp313-win_amd64.zip`:** хеші закріплено у `DIST-SHA256.txt` / `WHEELHOUSE-SHA256.txt`. **Відтворюваність збірки frontend і звірка wheel-ів з PyPI не виконувались** — залишковий ризик (див. §5).

## 4. V1 не використовується як джерело

- Tools ZIP зібрано лише з файлів `download/` (офіційні релізи).
- `clean-install.ps1` бере WinSW/Caddy лише з артефакту (`static-clean-install` CI-S3, CI-S4; мутація MCS2).
- Рядків і шляхів V1 у сценарії немає.

## 5. Залишкові ризики

| № | Ризик | Пропозиція |
| --- | --- | --- |
| P-1 | WinSW і Caddy без Authenticode; WinSW без опублікованих контрольних сум — довіра до GitHub-релізу (TLS) | №4: незалежне завантаження і звірка хешів |
| P-2 | Підпис sigstore для Caddy `checksums.txt` не перевірено | cosign на машині №4 |
| P-3 | Frontend dist і wheelhouse не перевірені на відтворюваність / PyPI-хеші | окреме завдання (за рішенням №5) |
| P-4 | Tools ZIP недетермінований (час запису в ZIP); незмінність = цей конкретний файл і його SHA256 | використовувати лише цей файл |
