#!/usr/bin/env bash
# ============================================================================
# Blinter Installer/Updater for Linux and macOS
# Purpose: Download and install the latest Blinter release for the current user
# Author: tboy1337
# Repository: https://github.com/BatchLang/Blinter
#
# Usage: install_blinter.sh [x64|arm64]
#
# The architecture is optional. Without it the build matches this machine. An
# argument overrides that, for example x64 on Apple Silicon to run under Rosetta.
#
# Installs to ${XDG_DATA_HOME:-$HOME/.local/share}/blinter/bin/blinter and adds
# that folder to PATH through a marked block in the shell startup files.
# Companion of install_blinter.cmd. Keep this file compatible with Bash 3.2,
# the version macOS ships as /bin/bash.
# ============================================================================
set -euo pipefail

readonly REPO_URL="https://github.com/BatchLang/Blinter"
readonly ISSUES_URL="https://github.com/BatchLang/Blinter/issues"
readonly TAG_PATTERN='^v[0-9]+\.[0-9]+\.[0-9]+$'
readonly DIGEST_PATTERN='^[0-9a-f]{64}$'
readonly MIN_DOWNLOAD_BYTES=500000
readonly MIN_GLIBC_MAJOR=2
readonly MIN_GLIBC_MINOR=39
readonly PATH_BLOCK_START='# >>> blinter >>>'
readonly PATH_BLOCK_END='# <<< blinter <<<'

# Selected build and detected host, filled in by the checks below.
REQUESTED_ARCH=""
OS_NAME=""
HOST_ARCH=""
TAG=""
EXPECTED_DIGEST=""
ASSET_NAME=""
ASSET_URL=""
EXTRACTED_EXE=""

# Install layout.
DATA_HOME=""
INSTALL_DIR=""
BIN_DIR=""
EXE=""
MARKER=""

# Install state used by the EXIT trap.
WORK_DIR=""
BACKUP_DIR=""
CURRENT_VERSION=""
NEEDS_BACKUP=0
INSTALL_TOUCHED=0

log() {
    printf '%s\n' "$*"
}

warn() {
    printf 'WARNING: %s\n' "$*" >&2
}

die() {
    printf 'ERROR: %s\n' "$*" >&2
    exit 1
}

print_usage() {
    log "Usage: install_blinter.sh [x64|arm64]"
}

# Put the previous installation back after a failed upgrade, or remove the
# half-installed files after a failed fresh install.
restore_previous_install() {
    if [[ ${INSTALL_TOUCHED} -ne 1 ]]; then
        return 0
    fi
    if [[ ${NEEDS_BACKUP} -eq 1 && -n ${BACKUP_DIR} ]]; then
        log ""
        log "Attempting to restore previous installation..."
        if [[ -f ${BACKUP_DIR}/blinter ]]; then
            cp -p "${BACKUP_DIR}/blinter" "${EXE}" || warn "Failed to restore blinter from backup."
        fi
        if [[ -f ${BACKUP_DIR}/installed_release.txt ]]; then
            cp -p "${BACKUP_DIR}/installed_release.txt" "${MARKER}" ||
                warn "Failed to restore installed_release.txt from backup."
        fi
        log "Previous installation restored."
        return 0
    fi
    log "Removing the incomplete installation..."
    rm -f -- "${EXE}" "${MARKER}"
    rmdir -- "${BIN_DIR}" "${INSTALL_DIR}" 2>/dev/null || true
}

on_exit() {
    local status=$?
    trap - EXIT
    if [[ ${status} -ne 0 ]]; then
        restore_previous_install || true
        log ""
        log "+--------------------------------------------------------+"
        log "+ Installation failed. Please review the errors above.   +"
        log "+--------------------------------------------------------+"
        log ""
        log "For help, visit: ${ISSUES_URL}"
    fi
    if [[ -n ${WORK_DIR} && -d ${WORK_DIR} ]]; then
        rm -rf -- "${WORK_DIR}"
    fi
    exit "${status}"
}

trap on_exit EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

# The architecture is optional. Without it the build matches this machine.
parse_arguments() {
    if [[ $# -eq 0 ]]; then
        return 0
    fi
    if [[ $# -eq 1 && ( $1 == "-h" || $1 == "--help" ) ]]; then
        print_usage
        exit 0
    fi
    if [[ $# -eq 1 && ( $1 == "x64" || $1 == "arm64" ) ]]; then
        REQUESTED_ARCH=$1
        return 0
    fi
    print_usage
    log ""
    log "The architecture argument was not recognized, so nothing was downloaded."
    exit 1
}

# Use the native build unless an architecture was given on the command line.
select_build() {
    if [[ -z ${REQUESTED_ARCH} ]]; then
        REQUESTED_ARCH=${HOST_ARCH}
        log "No architecture argument, using the native build."
    fi
    log "Selected build: ${REQUESTED_ARCH}"
    log ""
}

# Detect Linux or macOS and the CPU. Rosetta reports x86_64 from uname, so
# macOS asks the kernel whether the hardware is Apple Silicon.
detect_host() {
    local kernel machine native
    kernel=$(uname -s)
    machine=$(uname -m)
    case "${kernel}" in
        Linux) OS_NAME="Linux" ;;
        Darwin) OS_NAME="macOS" ;;
        *) die "Unsupported operating system: ${kernel}. Only Linux and macOS are supported." ;;
    esac
    case "${machine}" in
        x86_64 | amd64) HOST_ARCH="x64" ;;
        aarch64 | arm64) HOST_ARCH="arm64" ;;
        *) die "Unsupported CPU architecture: ${machine}." ;;
    esac
    if [[ ${OS_NAME} == "macOS" && ${HOST_ARCH} == "x64" ]]; then
        native=$(sysctl -n hw.optional.arm64 2>/dev/null || true)
        if [[ ${native} == "1" ]]; then
            HOST_ARCH="arm64"
        fi
    fi
    log "Detected host: ${OS_NAME} ${HOST_ARCH}"
}

# Refuse arm64 on a non-ARM machine and x64 on ARM Linux. x64 on Apple Silicon
# is allowed and runs through Rosetta.
check_architecture() {
    if [[ ${REQUESTED_ARCH} == "arm64" && ${HOST_ARCH} != "arm64" ]]; then
        die "The arm64 build cannot be installed on this machine. Nothing was downloaded."
    fi
    if [[ ${REQUESTED_ARCH} == "x64" && ${HOST_ARCH} == "arm64" ]]; then
        if [[ ${OS_NAME} == "Linux" ]]; then
            die "The x64 build cannot be installed on this ARM Linux machine. Use the arm64 argument. Nothing was downloaded."
        fi
        log "NOTE: This Mac has Apple Silicon. The x64 build runs through Rosetta. The arm64 argument installs the native build."
        log ""
    fi
}

# The Linux binaries are built against glibc 2.39. musl has no GNU_LIBC_VERSION.
check_glibc() {
    local libc version major minor
    if [[ ${OS_NAME} != "Linux" ]]; then
        return 0
    fi
    if ! libc=$(getconf GNU_LIBC_VERSION 2>/dev/null); then
        die "glibc ${MIN_GLIBC_MAJOR}.${MIN_GLIBC_MINOR} or newer is required, but glibc was not found (musl is not supported)."
    fi
    version=${libc#glibc }
    major=${version%%.*}
    minor=${version#*.}
    minor=${minor%%.*}
    if [[ ! ${major} =~ ^[0-9]+$ || ! ${minor} =~ ^[0-9]+$ ]]; then
        die "Could not parse the glibc version from '${libc}'."
    fi
    log "Detected glibc ${major}.${minor}"
    if ((major < MIN_GLIBC_MAJOR || (major == MIN_GLIBC_MAJOR && minor < MIN_GLIBC_MINOR))); then
        die "glibc ${MIN_GLIBC_MAJOR}.${MIN_GLIBC_MINOR} or newer is required, found ${major}.${minor}."
    fi
}

# The scripts are for a normal user, like the Windows scripts refuse admin.
check_not_root() {
    if [[ $(id -u) -eq 0 ]]; then
        die "This script is intended to be run as a user. Please run without root privileges."
    fi
}

check_tools() {
    local tool
    for tool in curl tar; do
        if ! command -v "${tool}" >/dev/null 2>&1; then
            die "${tool} is not installed or not in PATH."
        fi
    done
    if ! command -v sha256sum >/dev/null 2>&1 && ! command -v shasum >/dev/null 2>&1; then
        die "Neither sha256sum nor shasum is installed, so downloads cannot be verified."
    fi
}

sha256_of() {
    if command -v sha256sum >/dev/null 2>&1; then
        sha256sum -- "$1" | awk '{print tolower($1)}'
    else
        shasum -a 256 -- "$1" | awk '{print tolower($1)}'
    fi
}

resolve_layout() {
    if [[ -z ${HOME:-} || ${HOME} != /* ]]; then
        die "HOME must be set to an absolute path."
    fi
    DATA_HOME=${XDG_DATA_HOME:-}
    if [[ -z ${DATA_HOME} || ${DATA_HOME} != /* ]]; then
        DATA_HOME="${HOME}/.local/share"
    fi
    INSTALL_DIR="${DATA_HOME}/blinter"
    BIN_DIR="${INSTALL_DIR}/bin"
    EXE="${BIN_DIR}/blinter"
    MARKER="${INSTALL_DIR}/installed_release.txt"
}

# Read the latest release tag from the redirect of /releases/latest. This needs
# no JSON parser and does not use the rate-limited GitHub API.
resolve_latest_tag() {
    local effective
    if ! effective=$(curl -fsSL --connect-timeout 30 --max-time 60 --retry 3 \
        --proto '=https' --proto-redir '=https' \
        -o /dev/null -w '%{url_effective}' "${REPO_URL}/releases/latest"); then
        die "Failed to detect the latest Blinter version. Please check your internet connection and try again."
    fi
    if [[ ${effective} != "${REPO_URL}/releases/tag/"* ]]; then
        die "Unexpected release redirect: ${effective}"
    fi
    TAG=${effective##*/}
    if [[ ! ${TAG} =~ ${TAG_PATTERN} ]]; then
        die "Failed to parse Blinter version from '${effective}'."
    fi
    ASSET_NAME="Blinter-${TAG}-${OS_NAME}-${REQUESTED_ARCH}.tar.gz"
    ASSET_URL="${REPO_URL}/releases/download/${TAG}/${ASSET_NAME}"
    log "Latest Blinter ${REQUESTED_ARCH} release: ${TAG}"
    log ""
}

# Read this archive's SHA-256 line from the release SHA256SUMS file.
fetch_expected_digest() {
    local sums_file="${WORK_DIR}/SHA256SUMS"
    if ! curl -fsSL --connect-timeout 30 --max-time 60 --retry 3 \
        --proto '=https' --proto-redir '=https' \
        -o "${sums_file}" "${REPO_URL}/releases/download/${TAG}/SHA256SUMS"; then
        die "Failed to download SHA256SUMS for ${TAG}."
    fi
    EXPECTED_DIGEST=$(awk -v name="${ASSET_NAME}" \
        '$2 == name || $2 == "*" name { print tolower($1); exit }' "${sums_file}")
    if [[ -z ${EXPECTED_DIGEST} ]]; then
        log ""
        log "Refusing to install an unverifiable archive."
        die "GitHub release is missing a SHA256 digest for ${ASSET_NAME}. Cannot verify download."
    fi
    if [[ ! ${EXPECTED_DIGEST} =~ ${DIGEST_PATTERN} ]]; then
        die "SHA256SUMS contains an invalid digest for ${ASSET_NAME}: ${EXPECTED_DIGEST}"
    fi
}

# Work out whether this is a fresh install, an upgrade, a reinstall, or a no-op.
inspect_current_install() {
    local installed_release=""
    local binary_present=0
    if [[ -f ${EXE} ]]; then
        binary_present=1
        if [[ -x ${EXE} ]] && CURRENT_VERSION=$("${EXE}" --version 2>&1 | head -n 1); then
            log "Current installed version: ${CURRENT_VERSION}"
            log ""
        else
            CURRENT_VERSION=""
        fi
    fi
    if [[ -f ${MARKER} ]]; then
        IFS= read -r installed_release <"${MARKER}" || true
        if [[ ! ${installed_release} =~ ${TAG_PATTERN} ]]; then
            installed_release=""
        fi
    fi

    if [[ -n ${installed_release} && ${installed_release} == "${TAG}" ]]; then
        if [[ ${binary_present} -eq 1 && -n ${CURRENT_VERSION} ]]; then
            log "Blinter ${TAG} is already installed and up to date."
            exit 0
        fi
        log "Blinter ${TAG} is recorded as installed, but blinter is missing or did not run."
        log ""
        log "Reinstalling Blinter ${TAG}..."
        log ""
        NEEDS_BACKUP=${binary_present}
    elif [[ ${binary_present} -eq 1 && -n ${installed_release} ]]; then
        log "Upgrading from \"${installed_release}\" to ${TAG}..."
        log ""
        NEEDS_BACKUP=1
    elif [[ ${binary_present} -eq 1 ]]; then
        log "Existing installation found without release marker."
        log ""
        log "Upgrading to ${TAG}..."
        log ""
        NEEDS_BACKUP=1
    else
        log "No existing installation found."
        log ""
        log "Installing Blinter ${TAG}..."
        log ""
    fi
}

backup_current_install() {
    if [[ ${NEEDS_BACKUP} -ne 1 ]]; then
        return 0
    fi
    log "Creating backup of existing installation..."
    log ""
    BACKUP_DIR="${WORK_DIR}/backup"
    mkdir -p -- "${BACKUP_DIR}"
    cp -p "${EXE}" "${BACKUP_DIR}/blinter"
    if [[ -f ${MARKER} ]]; then
        cp -p "${MARKER}" "${BACKUP_DIR}/installed_release.txt"
    fi
}

download_archive() {
    local progress="-sS"
    if [[ -t 2 ]]; then
        progress="--progress-bar"
    fi
    log "Downloading Blinter ${TAG} from:"
    log "${ASSET_URL}"
    log ""
    if ! curl -fL --connect-timeout 30 --max-time 300 --retry 3 \
        --proto '=https' --proto-redir '=https' "${progress}" \
        -o "${WORK_DIR}/${ASSET_NAME}" "${ASSET_URL}"; then
        die "Failed to download Blinter. This could be due to network connectivity issues or an invalid download URL."
    fi
    if [[ ! -f ${WORK_DIR}/${ASSET_NAME} ]]; then
        die "Downloaded file not found at ${WORK_DIR}/${ASSET_NAME}"
    fi
}

verify_archive() {
    local size actual
    size=$(wc -c <"${WORK_DIR}/${ASSET_NAME}")
    size=${size//[[:space:]]/}
    if ((size < MIN_DOWNLOAD_BYTES)); then
        die "Downloaded file is too small (${size} bytes). Download may be corrupted."
    fi
    actual=$(sha256_of "${WORK_DIR}/${ASSET_NAME}")
    if [[ ${actual} != "${EXPECTED_DIGEST}" ]]; then
        die "SHA256 digest mismatch. The download may be corrupted or tampered with."
    fi
    log "SHA256 digest verified."
}

# The archive holds one folder named like the archive, containing blinter.
extract_archive() {
    local folder="${ASSET_NAME%.tar.gz}"
    local source="${WORK_DIR}/extract/${folder}/blinter"
    log ""
    log "Extracting Blinter..."
    log ""
    mkdir -p -- "${WORK_DIR}/extract"
    if ! tar -xzf "${WORK_DIR}/${ASSET_NAME}" -C "${WORK_DIR}/extract"; then
        die "Failed to extract Blinter archive."
    fi
    if [[ ! -f ${source} || -L ${source} ]]; then
        log "Expected layout: ${folder}/blinter"
        die "Blinter executable not found in extracted archive. The archive structure may have changed or be corrupted."
    fi
    EXTRACTED_EXE=${source}
}

# Stage the new file beside the target, then rename it. Replacing a running
# binary in place fails with "Text file busy" on Linux, but a rename works.
install_binary() {
    local staged="${BIN_DIR}/.blinter.new.$$"
    log "Installing Blinter executable..."
    log ""
    INSTALL_TOUCHED=1
    mkdir -p -- "${BIN_DIR}"
    cp -- "${EXTRACTED_EXE}" "${staged}"
    chmod 0755 -- "${staged}"
    if [[ ${OS_NAME} == "macOS" ]]; then
        xattr -d com.apple.quarantine "${staged}" 2>/dev/null || true
    fi
    if ! mv -f -- "${staged}" "${EXE}"; then
        rm -f -- "${staged}"
        die "Failed to install blinter. Check that you have write permission to ${BIN_DIR}."
    fi
    log "Installed blinter"
    log ""
    log "Verifying installation..."
    log ""
    if [[ ! -x ${EXE} ]]; then
        die "blinter not found after installation at ${EXE}"
    fi
    if ! "${EXE}" --version 2>&1; then
        die "blinter failed to execute."
    fi
}

write_release_marker() {
    if ! printf '%s\n' "${TAG}" >"${MARKER}"; then
        warn "Failed to write release marker at ${MARKER}"
    fi
}

# Quote a value so a POSIX shell reads it back unchanged.
shell_quote() {
    local escaped
    escaped=$(printf '%s' "$1" | sed "s/'/'\\\\''/g")
    printf "'%s'" "${escaped}"
}

# Print the marked PATH block that gets appended to a startup file.
path_block() {
    printf '%s\n' "${PATH_BLOCK_START}"
    printf '%s\n' "# Added by install_blinter.sh. uninstall_blinter.sh removes this block."
    printf 'blinter_bin=%s\n' "$(shell_quote "${BIN_DIR}")"
    # The remaining lines are shell code for the startup file and must stay unexpanded.
    # shellcheck disable=SC2016
    printf '%s\n' \
        'case ":${PATH}:" in' \
        '    *":${blinter_bin}:"*) ;;' \
        '    *) PATH="${PATH}:${blinter_bin}"; export PATH ;;' \
        'esac' \
        'unset blinter_bin'
    printf '%s\n' "${PATH_BLOCK_END}"
}

# Drop the marked block from stdin. An unterminated block is kept as it was, so
# a damaged file never loses the lines that follow the start marker.
strip_path_block() {
    awk -v start="${PATH_BLOCK_START}" -v finish="${PATH_BLOCK_END}" '
        skip {
            held = held "\n" $0
            if ($0 == finish) { skip = 0; held = "" }
            next
        }
        $0 == start { skip = 1; held = $0; next }
        { print }
        END { if (skip) print held }
    '
}

profile_has_current_block() {
    local file=$1 assignment
    assignment="blinter_bin=$(shell_quote "${BIN_DIR}")"
    grep -Fxq -- "${PATH_BLOCK_START}" "${file}" && grep -Fxq -- "${assignment}" "${file}"
}

# Names that always get the block, even when they do not exist yet.
profile_must_exist() {
    case "$1" in
        .profile) return 0 ;;
        .zshrc) [[ ${OS_NAME} == "macOS" ]] ;;
        *) return 1 ;;
    esac
}

update_one_profile() {
    local file=$1 stripped
    if profile_has_current_block "${file}"; then
        log "Blinter already in ${file}"
        return 0
    fi
    # The caller runs this in an if, which turns off set -e, so each step reports its own failure.
    if [[ -f ${file} ]]; then
        stripped="${WORK_DIR}/profile.stripped"
        strip_path_block <"${file}" >"${stripped}" || return 1
        # Write through the original path so permissions and symlinks survive.
        cat -- "${stripped}" >"${file}" || return 1
        if [[ -s ${file} && -n $(tail -c 1 -- "${file}") ]]; then
            printf '\n' >>"${file}" || return 1
        fi
    fi
    path_block >>"${file}" || return 1
    log "Blinter added to ${file}"
}

update_shell_profiles() {
    local name file failures=0
    log ""
    log "Updating PATH in shell startup files..."
    log ""
    for name in .profile .bashrc .zshrc .bash_profile; do
        file="${HOME}/${name}"
        if [[ ! -e ${file} ]] && ! profile_must_exist "${name}"; then
            continue
        fi
        if ! update_one_profile "${file}"; then
            warn "Failed to update ${file}."
            failures=$((failures + 1))
        fi
    done
    if [[ ${failures} -gt 0 ]]; then
        warn "You may need to manually add ${BIN_DIR} to your PATH."
    fi
    if command -v fish >/dev/null 2>&1 || [[ ${SHELL:-} == */fish ]]; then
        log "NOTE: fish does not read these files. Run: fish_add_path $(shell_quote "${BIN_DIR}")"
    fi
}

# The install folder is appended, so any blinter already on PATH keeps winning.
warn_if_shadowed() {
    local first
    first=$(command -v blinter 2>/dev/null || true)
    if [[ -n ${first} && ${first} != "${EXE}" ]]; then
        log ""
        warn "Another blinter is earlier on PATH and will run instead:"
        log "${first}"
        log "The standalone folder was appended and will not win:"
        log "${BIN_DIR}"
    fi
}

print_success() {
    log ""
    log "+============================================================+"
    log "+ SUCCESS: Blinter ${TAG} installed successfully!"
    log "+============================================================+"
    log ""
    log "Installation directory: ${BIN_DIR}"
    log ""
    log "Note: Open a new terminal, or run '. ~/.profile', to use Blinter commands."
    log ""
}

main() {
    parse_arguments "$@"
    log "+===========================+"
    log "+ Blinter Installer/Updater +"
    log "+===========================+"
    detect_host
    select_build
    check_architecture
    check_glibc
    check_not_root
    check_tools
    resolve_layout
    WORK_DIR=$(mktemp -d "${TMPDIR:-/tmp}/blinter_install.XXXXXX")
    log "Working directory: ${WORK_DIR}"
    resolve_latest_tag
    inspect_current_install
    fetch_expected_digest
    backup_current_install
    download_archive
    verify_archive
    extract_archive
    install_binary
    write_release_marker
    update_shell_profiles
    warn_if_shadowed
    print_success
}

main "$@"
