#!/usr/bin/env bash
# ============================================================================
# Blinter Uninstaller for Linux and macOS
# Purpose: Remove Blinter and its PATH block from the shell startup files
# Author: tboy1337
# Repository: https://github.com/BatchLang/Blinter
#
# Usage: uninstall_blinter.sh
#
# Companion of uninstall_blinter.cmd. Keep this file compatible with Bash 3.2,
# the version macOS ships as /bin/bash.
# ============================================================================
set -euo pipefail

readonly PATH_BLOCK_START='# >>> blinter >>>'
readonly PATH_BLOCK_END='# <<< blinter <<<'
readonly PROFILE_NAMES=(.profile .bashrc .zshrc .bash_profile)

DATA_HOME=""
INSTALL_DIR=""
BIN_DIR=""
EXE=""
MARKER=""
WORK_DIR=""
REMOVAL_FAILED=0

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

on_exit() {
    local status=$?
    trap - EXIT
    if [[ ${status} -ne 0 ]]; then
        log ""
        log "+----------------------------------------------------------+"
        log "+ Uninstallation failed. Please review the errors above.   +"
        log "+----------------------------------------------------------+"
        log ""
    fi
    if [[ -n ${WORK_DIR} && -d ${WORK_DIR} ]]; then
        rm -rf -- "${WORK_DIR}"
    fi
    exit "${status}"
}

trap on_exit EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

parse_arguments() {
    if [[ $# -eq 0 ]]; then
        return 0
    fi
    if [[ $# -eq 1 && ( $1 == "-h" || $1 == "--help" ) ]]; then
        log "Usage: uninstall_blinter.sh"
        exit 0
    fi
    log "Usage: uninstall_blinter.sh"
    exit 1
}

check_not_root() {
    if [[ $(id -u) -eq 0 ]]; then
        die "This script is intended to be run as a user. Please run without root privileges."
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

profile_has_block() {
    [[ -f $1 ]] && grep -Fxq -- "${PATH_BLOCK_START}" "$1"
}

any_profile_has_block() {
    local name
    for name in "${PROFILE_NAMES[@]}"; do
        if profile_has_block "${HOME}/${name}"; then
            return 0
        fi
    done
    return 1
}

show_installed_version() {
    local installed_release=""
    if [[ -x ${EXE} ]]; then
        log "Current installed version:"
        "${EXE}" --version 2>&1 || true
        log ""
    fi
    if [[ -f ${MARKER} ]]; then
        IFS= read -r installed_release <"${MARKER}" || true
        if [[ ${installed_release} =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
            log "Installed release: \"${installed_release}\""
            log ""
        fi
    fi
}

# Linux and macOS allow deleting a running executable, so unlike the Windows
# uninstaller there is no process to stop first. A running copy keeps working
# until it exits.
remove_files() {
    log "Removing Blinter files..."
    log ""
    if [[ -e ${EXE} || -L ${EXE} ]]; then
        if rm -f -- "${EXE}"; then
            log "Removed blinter"
        else
            warn "Failed to remove blinter."
            REMOVAL_FAILED=1
        fi
    fi
    if [[ -e ${MARKER} || -L ${MARKER} ]]; then
        if rm -f -- "${MARKER}"; then
            log "Removed installed_release.txt"
        else
            warn "Failed to remove installed_release.txt."
            REMOVAL_FAILED=1
        fi
    fi
}

remove_path_block_from() {
    local file=$1 stripped="${WORK_DIR}/profile.stripped"
    if ! profile_has_block "${file}"; then
        return 0
    fi
    # The caller runs this in an if, which turns off set -e, so each step reports its own failure.
    strip_path_block <"${file}" >"${stripped}" || return 1
    # Write through the original path so permissions and symlinks survive.
    if cmp -s -- "${file}" "${stripped}"; then
        warn "The Blinter block in ${file} has no end marker, so it was left unchanged."
        return 1
    fi
    cat -- "${stripped}" >"${file}" || return 1
    log "Blinter removed from ${file}"
}

remove_path_blocks() {
    local name
    log ""
    log "Removing Blinter from shell startup files..."
    log ""
    for name in "${PROFILE_NAMES[@]}"; do
        if ! remove_path_block_from "${HOME}/${name}"; then
            warn "Failed to remove the Blinter block from ${HOME}/${name}."
            log "You may need to delete the lines between '${PATH_BLOCK_START}' and '${PATH_BLOCK_END}' by hand."
            REMOVAL_FAILED=1
        fi
    done
}

# Only a folder literally named blinter is deleted recursively, so a wrong
# XDG_DATA_HOME can never point this at an unrelated directory.
remove_install_dir() {
    log ""
    log "Removing Blinter installation directory..."
    log ""
    if [[ ! -d ${INSTALL_DIR} ]]; then
        return 0
    fi
    if [[ ${INSTALL_DIR##*/} != "blinter" || ${INSTALL_DIR} == "/blinter" ]]; then
        warn "Refusing to delete unexpected directory: ${INSTALL_DIR}"
        REMOVAL_FAILED=1
        return 0
    fi
    if rm -rf -- "${INSTALL_DIR}"; then
        log "Installation directory removed: ${INSTALL_DIR}"
    else
        warn "Failed to remove installation directory."
        log "You can manually delete: ${INSTALL_DIR}"
        REMOVAL_FAILED=1
    fi
}

print_result() {
    log ""
    if [[ ${REMOVAL_FAILED} -eq 1 ]]; then
        log "+========================================+"
        log "+ Uninstallation completed with warnings +"
        log "+========================================+"
        log ""
        log "Some files or directories could not be removed."
        log "Please review the warnings above and take manual action if needed."
    else
        log "+============================================+"
        log "+ SUCCESS: Blinter uninstalled successfully! +"
        log "+============================================+"
    fi
    log ""
    log "Note: Open a new terminal for PATH changes to take effect."
    log ""
}

main() {
    parse_arguments "$@"
    log "+=====================+"
    log "+ Blinter Uninstaller +"
    log "+=====================+"
    log ""
    check_not_root
    resolve_layout
    WORK_DIR=$(mktemp -d "${TMPDIR:-/tmp}/blinter_uninstall.XXXXXX")
    if [[ ! -d ${INSTALL_DIR} ]] && ! any_profile_has_block; then
        log "Blinter installation not found at: ${INSTALL_DIR}"
        log ""
        log "Nothing to uninstall."
        exit 0
    fi
    show_installed_version
    log "Removing Blinter from: ${INSTALL_DIR}"
    log ""
    remove_files
    remove_path_blocks
    remove_install_dir
    print_result
}

main "$@"
