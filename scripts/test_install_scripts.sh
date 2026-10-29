#!/usr/bin/env bash
# ============================================================================
# End-to-end test of install_blinter.sh and uninstall_blinter.sh
# Used by Linux and macOS CI. Counterpart of test_install_scripts.ps1.
#
# Usage: test_install_scripts.sh [x64|arm64]
#
# Runs the real scripts against the latest GitHub release, with a temporary
# HOME so the real user's startup files and install are never touched. The
# argument is the architecture the installer is expected to select, and it
# defaults to the native one. The first scenario runs the installer with no
# architecture so auto-detection is tested, and the second names it.
# ============================================================================
set -euo pipefail

readonly VERSION_PATTERN='^v[0-9]+\.[0-9]+\.[0-9]+ \((standalone exe|Python [0-9]+\.[0-9]+, .+)\)$'
readonly START_MARKER='# >>> blinter >>>'

SCRIPTS_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
readonly SCRIPTS_DIR
WORK_DIR=""
ARCH=""
LAST_OUTPUT=""
LAST_STATUS=0

log() {
    printf 'installer-test: %s\n' "$*"
}

fail() {
    printf 'installer-test: FAIL: %s\n' "$*" >&2
    if [[ -n ${LAST_OUTPUT} ]]; then
        printf '%s\n' "--- last script output ---" "${LAST_OUTPUT}" "--------------------------" >&2
    fi
    exit 1
}

cleanup() {
    if [[ -n ${WORK_DIR} && -d ${WORK_DIR} ]]; then
        rm -rf -- "${WORK_DIR}"
    fi
}

native_arch() {
    case "$(uname -m)" in
        x86_64 | amd64) printf 'x64\n' ;;
        aarch64 | arm64) printf 'arm64\n' ;;
        *) fail "Unsupported CPU: $(uname -m)" ;;
    esac
}

# Run a script under bash and keep its combined output and exit status.
run_script() {
    local script=$1
    shift
    log "Running ${script##*/} $*"
    LAST_STATUS=0
    LAST_OUTPUT=$(/bin/bash "${script}" "$@" 2>&1) || LAST_STATUS=$?
    log "Finished ${script##*/} exit=${LAST_STATUS}"
}

assert_status() {
    if [[ ${LAST_STATUS} -ne $1 ]]; then
        fail "Expected exit $1 but got ${LAST_STATUS}."
    fi
}

assert_output_contains() {
    if [[ ${LAST_OUTPUT} != *"$1"* ]]; then
        fail "Output did not contain '$1'."
    fi
}

assert_output_lacks() {
    if [[ ${LAST_OUTPUT} == *"$1"* ]]; then
        fail "Output contained forbidden text '$1'."
    fi
}

install_dir() {
    printf '%s\n' "${HOME}/.local/share/blinter"
}

assert_installed() {
    local exe marker version tag found
    exe="$(install_dir)/bin/blinter"
    marker="$(install_dir)/installed_release.txt"
    [[ -x ${exe} ]] || fail "blinter was not installed at ${exe}"
    version=$("${exe}" --version 2>&1 | head -n 1)
    log "Installed version: ${version}"
    if [[ ! ${version} =~ ${VERSION_PATTERN} ]]; then
        fail "Unexpected blinter --version output: ${version}"
    fi
    tag=${version%% *}
    [[ $(cat -- "${marker}") == "${tag}" ]] || fail "Release marker does not match ${tag}"
    grep -Fxq -- "${START_MARKER}" "${HOME}/.profile" || fail "${HOME}/.profile has no Blinter PATH block"
    # A new login shell must find the install through the startup file alone.
    for shell in /bin/sh /bin/bash; do
        # The single-quoted command must expand in the child shell, not here.
        # shellcheck disable=SC2016
        found=$(env -i HOME="${HOME}" PATH="/usr/bin:/bin" "${shell}" -c '. "${HOME}/.profile"; command -v blinter')
        [[ ${found} == "${exe}" ]] || fail "${shell} found '${found}' instead of ${exe}"
    done
}

assert_removed() {
    local name
    [[ ! -e $(install_dir) ]] || fail "Install directory still exists at $(install_dir)"
    for name in .profile .bashrc .zshrc .bash_profile; do
        if [[ -f ${HOME}/${name} ]] && grep -Fxq -- "${START_MARKER}" "${HOME}/${name}"; then
            fail "${HOME}/${name} still has the Blinter PATH block"
        fi
    done
    log "Install directory and PATH block removed"
}

assert_install_refused() {
    local label=$1 pattern=$2
    shift 2
    run_script "${SCRIPTS_DIR}/install_blinter.sh" "$@"
    assert_status 1
    assert_output_contains "${pattern}"
    assert_output_lacks "Extracting Blinter"
    [[ ! -e $(install_dir) ]] || fail "Refused install created $(install_dir)"
    log "Refused install ${label}"
}

run_scenario() {
    local name=$1 script_dir=$2 install_args=${3:-}
    log "Scenario ${name} (install arguments: '${install_args}')"
    # install_args is empty for auto-detection, so it is left unquoted on purpose.
    # shellcheck disable=SC2086
    run_script "${script_dir}/install_blinter.sh" ${install_args}
    assert_status 0
    assert_output_contains "Selected build: ${ARCH}"
    assert_output_contains "SUCCESS: Blinter"
    assert_output_lacks "Installation failed"
    assert_installed

    # shellcheck disable=SC2086
    run_script "${script_dir}/install_blinter.sh" ${install_args}
    assert_status 0
    assert_output_contains "already installed and up to date"
    assert_installed

    run_script "${script_dir}/uninstall_blinter.sh"
    assert_status 0
    assert_output_contains "SUCCESS: Blinter uninstalled successfully"
    assert_output_lacks "completed with warnings"
    assert_removed
    log "Scenario ${name} passed"
}

main() {
    local copy_dir
    ARCH=${1:-$(native_arch)}
    if [[ ${ARCH} != "x64" && ${ARCH} != "arm64" ]]; then
        fail "Architecture must be x64 or arm64, got '${ARCH}'."
    fi
    if [[ $(id -u) -eq 0 ]]; then
        fail "Run this test as a normal user. The installer refuses root."
    fi

    WORK_DIR=$(mktemp -d "${TMPDIR:-/tmp}/blinter-install-ci.XXXXXX")
    trap cleanup EXIT
    export HOME="${WORK_DIR}/home"
    export TMPDIR="${WORK_DIR}/tmp"
    unset XDG_DATA_HOME
    mkdir -p -- "${HOME}" "${TMPDIR}"
    log "Work directory: ${WORK_DIR}"
    log "Architecture: ${ARCH} on $(uname -s) $(uname -m)"

    run_script "${SCRIPTS_DIR}/uninstall_blinter.sh"
    assert_status 0
    assert_output_contains "Nothing to uninstall"

    assert_install_refused "bad argument" "Usage: install_blinter.sh [x64|arm64]" sparc
    if [[ $(native_arch) == "x64" ]]; then
        assert_install_refused "arm64 on x64" "cannot be installed on this machine" arm64
    elif [[ $(uname -s) == "Linux" ]]; then
        assert_install_refused "x64 on ARM Linux" "cannot be installed on this ARM Linux machine" x64
    fi

    # No argument: the installer must pick the native build on its own.
    run_scenario "repository" "${SCRIPTS_DIR}"

    # The README downloads the script next to the user's files, which may sit in a
    # folder whose name has spaces. This run names the architecture explicitly.
    copy_dir="${WORK_DIR}/copy with spaces"
    mkdir -p -- "${copy_dir}"
    cp -- "${SCRIPTS_DIR}/install_blinter.sh" "${SCRIPTS_DIR}/uninstall_blinter.sh" "${copy_dir}/"
    run_scenario "downloaded-copy" "${copy_dir}" "${ARCH}"

    log "Installer and uninstaller passed"
}

main "$@"
