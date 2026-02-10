#!/usr/bin/env bash
set -euo pipefail

# MindType whisper.cpp model mirror bootstrap.
# - Downloads ggml-*.bin models (tiny/small/medium/large-v3) from HF mirrors
# - Optionally configures Caddy to serve them as static files
#
# Typical usage (Ubuntu/Debian, with Caddy already running for mindtype.space):
#   sudo ./setup_whispercpp_model_mirror.sh \
#     --hosts "mindtype.space cdn.mindtype.space" \
#     --models-dir /var/www/mindtype/models/whispercpp \
#     --configure-caddy
#
# If you want to host elsewhere, you can later set MindType "Model download sources"
# to your base URL, e.g. https://models.example.com/whispercpp

REPO_ID="ggerganov/whisper.cpp"

HOSTS=""
MODELS_DIR="/var/www/mindtype/models/whispercpp"
PATH_PREFIX="/models/whispercpp"
CADDYFILE="/etc/caddy/Caddyfile"
SNIPPET_PATH="/etc/caddy/snippets/mindtype-whispercpp-models.caddy"
CONFIGURE_CADDY="0"
RELOAD_CADDY="1"
SKIP_LARGE="0"

# Comma-separated list of upstream bases to try (will append /<filename>).
UPSTREAMS_DEFAULT="https://hf-mirror.com/${REPO_ID}/resolve/main,https://huggingface.co/${REPO_ID}/resolve/main"
UPSTREAMS="${UPSTREAMS_DEFAULT}"

usage() {
  cat <<EOF
Usage:
  $(basename "$0") [options]

Options:
  --hosts "mindtype.space [cdn.mindtype.space ...]"   Hosts served by your Caddy site block (required for --configure-caddy).
  --models-dir /var/www/...                           Directory to store ggml-*.bin (default: ${MODELS_DIR})
  --path-prefix /models/whispercpp                    URL path prefix to serve from (default: ${PATH_PREFIX})
  --upstreams "base1,base2,..."                       Upstream bases (default: ${UPSTREAMS_DEFAULT})
  --skip-large                                        Don't download ggml-large-v3.bin
  --configure-caddy                                   Create snippet + patch Caddyfile + validate + reload
  --caddyfile /etc/caddy/Caddyfile                    Caddyfile path (default: ${CADDYFILE})
  --no-reload                                         Don't reload Caddy (only validate/patch)
  -h, --help                                          Show help

Examples:
  Download only:
    sudo $(basename "$0") --models-dir /var/www/mindtype/models/whispercpp

  Download + configure Caddy (recommended):
    sudo $(basename "$0") --hosts "mindtype.space" --configure-caddy
EOF
}

die() {
  echo "ERROR: $*" >&2
  exit 1
}

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "Missing dependency: $1"
}

as_root_prefix() {
  if [[ "${EUID:-$(id -u)}" -eq 0 ]]; then
    echo ""
  else
    echo "sudo"
  fi
}

parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --hosts)
        HOSTS="${2:-}"; shift 2;;
      --models-dir)
        MODELS_DIR="${2:-}"; shift 2;;
      --path-prefix)
        PATH_PREFIX="${2:-}"; shift 2;;
      --upstreams)
        UPSTREAMS="${2:-}"; shift 2;;
      --skip-large)
        SKIP_LARGE="1"; shift 1;;
      --configure-caddy)
        CONFIGURE_CADDY="1"; shift 1;;
      --caddyfile)
        CADDYFILE="${2:-}"; shift 2;;
      --no-reload)
        RELOAD_CADDY="0"; shift 1;;
      -h|--help)
        usage; exit 0;;
      *)
        die "Unknown option: $1";;
    esac
  done
}

parse_content_length() {
  # Reads headers from stdin, prints the LAST numeric Content-Length (or empty).
  # With -L curl prints headers for redirects too; we want the final response size.
  awk '
    BEGIN{IGNORECASE=1}
    $1=="content-length:"{
      gsub("\r","",$2);
      if ($2 ~ /^[0-9]+$/) { val=$2 }
    }
    END{ if (val) print val }
  '
}

download_one() {
  local filename="$1"
  local upstream_bases="$2"
  local dest_dir="$3"

  mkdir -p "$dest_dir"

  local dest="$dest_dir/$filename"
  local part="$dest.part"

  # If a complete file already exists, keep it.
  if [[ -f "$dest" ]]; then
    local sz
    sz="$(stat -c%s "$dest" 2>/dev/null || stat -f%z "$dest" 2>/dev/null || echo "")"
    if [[ -n "$sz" && "$sz" -ge $((5 * 1024 * 1024)) ]]; then
      echo "[OK] $filename already present ($sz bytes)"
      return 0
    fi
    echo "[WARN] $filename exists but looks too small; will re-download"
    mv -f "$dest" "$part" 2>/dev/null || true
  fi

  local IFS=,
  for base in $upstream_bases; do
    base="$(echo "$base" | xargs)"
    [[ -n "$base" ]] || continue
    local url="${base%/}/$filename"
    echo "[..] $filename <- $url"

    # Try to discover expected size (optional).
    local expected=""
    if expected="$(curl -fsSLI --connect-timeout 10 "$url" 2>/dev/null | parse_content_length || true)"; then
      expected="${expected:-}"
    else
      expected=""
    fi
    # Some providers return a small Content-Length for redirects/error pages; ignore it.
    if [[ -n "$expected" && "$expected" -lt $((5 * 1024 * 1024)) ]]; then
      expected=""
    fi

    # If we have a partial file and expected size matches, finalize.
    if [[ -f "$part" && -n "$expected" ]]; then
      local psz
      psz="$(stat -c%s "$part" 2>/dev/null || stat -f%z "$part" 2>/dev/null || echo "")"
      if [[ -n "$psz" && "$psz" -eq "$expected" ]]; then
        mv -f "$part" "$dest"
        echo "[OK] $filename already complete ($expected bytes)"
        return 0
      fi
    fi

    # Download with resume into .part (Range supported by HF and typical static servers).
    set +e
    curl -fL --progress-bar \
      --retry 5 --retry-delay 2 --retry-all-errors \
      --connect-timeout 10 \
      -C - -o "$part" \
      "$url"
    local rc=$?
    set -e
    if [[ $rc -ne 0 ]]; then
      echo "[WARN] failed ($rc): $url" >&2
      continue
    fi

    # Basic sanity checks.
    local got
    got="$(stat -c%s "$part" 2>/dev/null || stat -f%z "$part" 2>/dev/null || echo "")"
    if [[ -z "$got" || "$got" -lt $((5 * 1024 * 1024)) ]]; then
      echo "[WARN] downloaded file looks too small ($got bytes): $url" >&2
      rm -f "$part" 2>/dev/null || true
      continue
    fi
    if [[ -n "$expected" && "$got" -ne "$expected" ]]; then
      echo "[WARN] size mismatch: got $got, expected $expected: $url" >&2
      # Keep .part for resume and try again from the same URL next run.
      continue
    fi

    mv -f "$part" "$dest"
    chmod 0644 "$dest" || true
    echo "[OK] downloaded: $dest ($got bytes)"
    return 0
  done

  return 1
}

write_caddy_snippet() {
  local snippet_path="$1"
  local models_dir="$2"
  local path_prefix="$3"

  mkdir -p "$(dirname "$snippet_path")"
  cat >"$snippet_path" <<EOF
# Auto-generated by $(basename "$0")
# Serves MindType whisper.cpp models at ${path_prefix}/<filename>
handle_path ${path_prefix}/* {
  root * ${models_dir}
  file_server
}
EOF
}

patch_caddyfile_import() {
  local caddyfile="$1"
  local snippet_path="$2"
  local hosts="$3"

  [[ -f "$caddyfile" ]] || die "Caddyfile not found: $caddyfile"

  if grep -Fq "$snippet_path" "$caddyfile"; then
    echo "[OK] Caddyfile already references snippet: $snippet_path"
    return 0
  fi

  # Insert "import <snippet>" into the first matching site block line that contains any host.
  # This is intentionally simple; we create a backup and validate after patching.
  local backup="${caddyfile}.bak.$(date +%Y%m%d_%H%M%S)"
  cp -a "$caddyfile" "$backup"
  echo "[..] backup: $backup"

  local host_re=""
  for h in $hosts; do
    h="$(echo "$h" | xargs)"
    [[ -n "$h" ]] || continue
    # Match as a token (space/comma separated) on a site block start line.
    # Example lines:
    #   mindtype.space {
    #   mindtype.space, cdn.mindtype.space {
    #   https://mindtype.space {
    local escaped
    escaped="$(printf '%s' "$h" | sed 's/[.[\\*^$(){}+?|]/\\\\&/g')"
    if [[ -z "$host_re" ]]; then
      # Allow optional scheme prefix and optional :port suffix.
      host_re="(^|[[:space:],]|https?://)${escaped}(:[0-9]+)?([[:space:],]|$)"
    else
      host_re="${host_re}|(^|[[:space:],]|https?://)${escaped}(:[0-9]+)?([[:space:],]|$)"
    fi
  done

  [[ -n "$host_re" ]] || die "--hosts is required for --configure-caddy"

  local tmp="${caddyfile}.tmp.$$"
  set +e
  awk -v host_re="$host_re" -v import_line="  import ${snippet_path}" '
    BEGIN { inserted=0 }
    {
      print $0
      if (inserted==0 && $0 ~ /\{/ && $0 !~ /^[[:space:]]*\{/ && $0 ~ host_re) {
        print import_line
        inserted=1
      }
    }
    END { if (inserted==0) { exit 2 } }
  ' "$caddyfile" >"$tmp"
  local rc=$?
  set -e

  if [[ $rc -eq 2 ]]; then
    rm -f "$tmp" 2>/dev/null || true
    die "Couldn't find a Caddy site block for hosts: $hosts. Add this line manually inside your site block:  import ${snippet_path}"
  fi
  if [[ $rc -ne 0 ]]; then
    rm -f "$tmp" 2>/dev/null || true
    die "Failed to patch Caddyfile (awk rc=$rc)"
  fi

  mv -f "$tmp" "$caddyfile"
  echo "[OK] Patched Caddyfile: added import ${snippet_path}"
}

validate_and_reload_caddy() {
  local caddyfile="$1"
  local reload="$2"

  need_cmd caddy

  echo "[..] caddy validate"
  caddy validate --config "$caddyfile" --adapter caddyfile

  if [[ "$reload" == "1" ]]; then
    if command -v systemctl >/dev/null 2>&1 && systemctl is-active --quiet caddy 2>/dev/null; then
      echo "[..] systemctl reload caddy"
      systemctl reload caddy
    else
      # Best-effort reload via admin API (may fail depending on deployment).
      echo "[..] caddy reload"
      caddy reload --config "$caddyfile" --adapter caddyfile || true
    fi
  else
    echo "[..] --no-reload selected, not reloading Caddy"
  fi
}

main() {
  parse_args "$@"
  need_cmd curl

  local models=("tiny" "small" "medium" "large-v3")
  if [[ "$SKIP_LARGE" == "1" ]]; then
    models=("tiny" "small" "medium")
  fi

  echo "[..] models dir: $MODELS_DIR"
  mkdir -p "$MODELS_DIR"
  chmod 0755 "$MODELS_DIR" || true

  for m in "${models[@]}"; do
    local filename="ggml-${m}.bin"
    if ! download_one "$filename" "$UPSTREAMS" "$MODELS_DIR"; then
      die "Failed to download $filename from all upstreams. You can override with --upstreams"
    fi
  done

  echo "[OK] All requested models are present in: $MODELS_DIR"

  if [[ "$CONFIGURE_CADDY" == "1" ]]; then
    echo "[..] configuring Caddy"
    write_caddy_snippet "$SNIPPET_PATH" "$MODELS_DIR" "$PATH_PREFIX"
    chmod 0644 "$SNIPPET_PATH" || true
    echo "[OK] wrote snippet: $SNIPPET_PATH"

    patch_caddyfile_import "$CADDYFILE" "$SNIPPET_PATH" "$HOSTS"
    validate_and_reload_caddy "$CADDYFILE" "$RELOAD_CADDY"

    echo "[OK] Static serving should work now:"
    echo "     https://<your-host>${PATH_PREFIX}/ggml-small.bin"
  else
    echo "[..] Caddy not configured. To serve static files via Caddy, run with:"
    echo "     --hosts \"mindtype.space\" --configure-caddy"
    echo ""
    echo "Caddy snippet (inside your site block):"
    echo "  import $SNIPPET_PATH"
  fi
}

main "$@"
