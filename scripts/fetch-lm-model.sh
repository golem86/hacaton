#!/usr/bin/env sh
# fetch-lm-model.sh — завантаження моделі Qwen3-8B-Q4_K_M.gguf (Hugging Face Qwen/Qwen3-8B-GGUF, 5,03 ГБ) у ./models для
# Docker-сервісу lm (compose --profile lm) з перевіркою SHA256. Кінцеве ім'я — лише після збігу SHA256; до того <ім'я>.partial
# (curl докачує його при повторному запуску). Модель у Git не потрапляє (.gitignore: models/).
#   sh scripts/fetch-lm-model.sh [каталог=./models] [ревізія=main]
set -eu
FILE="Qwen3-8B-Q4_K_M.gguf"
SHA256="d98cdcbd03e17ce47681435b5150e34c1417f50b5c0019dd560e4882c5745785"
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
DEST="${1:-$ROOT/models}"
REV="${2:-main}"
case "$REV" in *[!A-Za-z0-9._-]*|'') echo "некоректна ревізія: $REV" >&2; exit 2;; esac
URL="https://huggingface.co/Qwen/Qwen3-8B-GGUF/resolve/$REV/$FILE"

sha() {
  if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | cut -d' ' -f1
  else shasum -a 256 "$1" | cut -d' ' -f1; fi
}

mkdir -p "$DEST"
TARGET="$DEST/$FILE"
PARTIAL="$TARGET.partial"
if [ -f "$TARGET" ]; then
  if [ "$(sha "$TARGET")" = "$SHA256" ]; then echo "OK  $TARGET уже є, SHA256 збігається"; exit 0; fi
  echo "$TARGET існує, але SHA256 не збігається — видаліть його вручну" >&2; exit 1
fi
echo "Завантаження $URL -> $PARTIAL"
curl --fail --location --retry 5 --retry-delay 5 --continue-at - --output "$PARTIAL" "$URL"
GOT=$(sha "$PARTIAL")
if [ "$GOT" != "$SHA256" ]; then
  rm -f "$PARTIAL"
  echo "SHA256 $GOT != очікуваному $SHA256 — файл видалено" >&2; exit 1
fi
mv "$PARTIAL" "$TARGET"
echo "OK  $TARGET (SHA256 $GOT)"
