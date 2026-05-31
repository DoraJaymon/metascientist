#!/bin/sh

set -eu

TARGET_DIR="${METASCI_SKILLS_DIR:-}"
SOURCE_DIR="${METASCI_INSTALL_SKILLS_SOURCE_DIR:-}"
ARCHIVE_URL="${METASCI_INSTALL_SKILLS_ARCHIVE_URL:-}"
WITH_RUNTIME=0
RUNTIME_SPEC="${METASCI_RUNTIME_SPEC:-}"

step() {
  printf '==> %s\n' "$1"
}

usage() {
  cat >&2 <<'USAGE'
Usage: install-codex-skills.sh [--user] [--dir <path>] [--source <path>]
                               [--archive-url <url>] [--with-runtime]
                               [--runtime <uv-tool-spec>]

Installs the MetaSci Codex skill bundle. Runtime installation is optional.

Examples:
  sh scripts/install/install-codex-skills.sh --user
  sh scripts/install/install-codex-skills.sh --user --with-runtime
  sh scripts/install/install-codex-skills.sh --with-runtime --runtime ./metasci-universe
USAGE
}

download_file() {
  url="$1"
  output="$2"

  if command -v curl >/dev/null 2>&1; then
    if [ -t 2 ]; then
      curl -fL --progress-bar "$url" -o "$output"
    else
      curl -fsSL "$url" -o "$output"
    fi
    return
  fi

  if command -v wget >/dev/null 2>&1; then
    if [ -t 2 ]; then
      wget --show-progress -O "$output" "$url"
    else
      wget -q -O "$output" "$url"
    fi
    return
  fi

  echo "curl or wget is required to download MetaSci skills." >&2
  exit 1
}

resolve_target_dir() {
  if [ -n "$TARGET_DIR" ]; then
    printf '%s\n' "$TARGET_DIR"
    return
  fi

  codex_home="${CODEX_HOME:-$HOME/.codex}"
  printf '%s/skills/metasci\n' "$codex_home"
}

check_source_root() {
  candidate="$1"
  if [ -d "$candidate/metasci-skills/skills" ] && [ -d "$candidate/metasci-universe" ]; then
    printf '%s\n' "$candidate"
    return 0
  fi
  return 1
}

resolve_local_source_root() {
  if [ -n "$SOURCE_DIR" ]; then
    if check_source_root "$SOURCE_DIR"; then
      return
    fi
    echo "Source directory does not contain metasci-skills/skills and metasci-universe: $SOURCE_DIR" >&2
    exit 1
  fi

  script_dir="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
  repo_candidate="$(CDPATH= cd -- "$script_dir/../.." && pwd)"
  if check_source_root "$repo_candidate"; then
    return
  fi

  if check_source_root "$PWD"; then
    return
  fi

  return 1
}

resolve_archive_source_root() {
  archive_url="$1"
  tmp_dir="$2"

  archive_path="$tmp_dir/metasci-skills.tar.gz"
  extract_dir="$tmp_dir/extract"

  step "Downloading skills archive"
  download_file "$archive_url" "$archive_path"

  mkdir -p "$extract_dir"
  step "Extracting skills"
  tar -xzf "$archive_path" -C "$extract_dir"

  source_root="$(find "$extract_dir" -mindepth 1 -maxdepth 1 -type d | head -n 1)"
  if [ -z "$source_root" ] || ! check_source_root "$source_root" >/dev/null; then
    echo "Could not find metasci-skills/skills and metasci-universe in the archive." >&2
    exit 1
  fi

  printf '%s\n' "$source_root"
}

install_runtime() {
  source_root="$1"

  if [ "$WITH_RUNTIME" -ne 1 ]; then
    return
  fi

  if ! command -v uv >/dev/null 2>&1; then
    echo "uv is required for --with-runtime. Install uv or omit --with-runtime." >&2
    exit 1
  fi

  runtime_spec="$RUNTIME_SPEC"
  if [ -z "$runtime_spec" ]; then
    runtime_spec="$source_root/metasci-universe"
  fi

  step "Installing MetaSci runtime with uv"
  uv tool install --force --refresh "$runtime_spec"
}

while [ $# -gt 0 ]; do
  case "$1" in
    --user)
      # User-level Codex installation is the default and only built-in scope.
      ;;
    --dir)
      if [ $# -lt 2 ]; then
        usage
        exit 1
      fi
      TARGET_DIR="$2"
      shift
      ;;
    --source)
      if [ $# -lt 2 ]; then
        usage
        exit 1
      fi
      SOURCE_DIR="$2"
      shift
      ;;
    --archive-url)
      if [ $# -lt 2 ]; then
        usage
        exit 1
      fi
      ARCHIVE_URL="$2"
      shift
      ;;
    --with-runtime)
      WITH_RUNTIME=1
      ;;
    --runtime)
      if [ $# -lt 2 ]; then
        usage
        exit 1
      fi
      RUNTIME_SPEC="$2"
      WITH_RUNTIME=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      exit 1
      ;;
  esac
  shift
done

tmp_dir="$(mktemp -d)"
cleanup() {
  rm -rf "$tmp_dir"
}
trap cleanup EXIT INT TERM

if [ -n "$ARCHIVE_URL" ]; then
  source_root="$(resolve_archive_source_root "$ARCHIVE_URL" "$tmp_dir")"
else
  if ! source_root="$(resolve_local_source_root)"; then
    echo "Could not locate a MetaSci source tree. Use --source or --archive-url." >&2
    exit 1
  fi
fi

install_dir="$(resolve_target_dir)"

step "Installing MetaSci skills"
mkdir -p "$(dirname "$install_dir")"
rm -rf "$install_dir"
mkdir -p "$install_dir"

cp -R "$source_root/metasci-skills/skills" "$install_dir/skills"
if [ -f "$source_root/metasci-skills/AGENTS.md" ]; then
  cp "$source_root/metasci-skills/AGENTS.md" "$install_dir/AGENTS.md"
fi

install_runtime "$source_root"

step "Installed MetaSci skills to $install_dir"
