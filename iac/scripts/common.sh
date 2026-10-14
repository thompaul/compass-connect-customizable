#!/usr/bin/env bash

# Global variables

# The directory where the script is located.
SCRIPT_DIR="$(realpath "$(dirname "${BASH_SOURCE[0]}")")" # The directory where the script is located.
echo "info: setting the script directory to $SCRIPT_DIR"

# Root path
ROOT_PATH="$(realpath "$SCRIPT_DIR/../../")"
echo "info: setting the root path to $ROOT_PATH"

# Global Functions
real_file_path() {
    local path="$1"

    # Remove trailing slash to ensure consistent behavior
    path="${path%/}"

    # Resolve the absolute path of the parent directory
    local abs_dir
    abs_dir=$(cd "$(dirname "$path")" 2>/dev/null && pwd -P)

    # Append the original filename to reconstruct the full absolute path
    echo "$abs_dir/$(basename "$path")"
}


function get_git_sha() {
  git rev-parse HEAD
}

function get_git_branch_tag_name() {
  git describe --exact-match --tags HEAD 2>/dev/null || git rev-parse --abbrev-ref HEAD
}

function get_docker_tag() {
  # get the tag name or branch name
  local _git_branch_tag_name
  _git_branch_tag_name="$(get_git_branch_tag_name)"

  local _git_commit_sha
  _git_commit_sha="$(get_git_sha)"

  _artifact_version="$("$SCRIPT_DIR/formatters.py" --branch-name="$_git_branch_tag_name" --git-sha="$_git_commit_sha" --version=docker-tag)"

  echo -n "$_artifact_version" # this is the return value
}

function get_generic_artifacts_version() {
  # get the tag name or branch name
  local _git_branch_tag_name
  _git_branch_tag_name="$(get_git_branch_tag_name)"

  local _git_commit_sha
  _git_commit_sha="$(get_git_sha)"

  local _artifact_version
  _artifact_version="$("${SCRIPT_DIR}/formatters.py" --branch-name="$_git_branch_tag_name" --git-sha="$_git_commit_sha" --version=generic-artifacts)"

  echo -n "$_artifact_version" # this is the return value
}

function upload_file() {
  local _region=$1
  local _project_id=$2
  local _artifact_version=$3
  local _directory_path=$4
  local _file_name=$5

  local _file_path="$_directory_path/$_file_name"

  echo "info uploading the file $_file_path"

  # Test if the files exists before deleting
  if [ -z "$(gcloud artifacts files list \
          --repository=generic-repository \
          --location="$_region" \
          --project="$_project_id" \
          --package=artifacts \
          --version="$_artifact_version" \
          --format="value(name)" \
          --filter="name:$_file_name")" ]; then
    echo "info: file does not exist, skipping deletion"
  else
    echo "info: deleting the existing file:$_artifact_version"
    gcloud artifacts files delete "artifacts:$_artifact_version:$_file_name" \
      --repository=generic-repository \
      --location="$_region" \
      --project="$_project_id" \
      --quiet
  fi

  # Then upload the file
  echo "info: uploading the file: $_file_name"

  if ! gcloud artifacts generic upload --package=artifacts \
           --repository=generic-repository \
           --location="$_region" \
           --source="$_file_path" \
           --project="$_project_id" \
           --version="$_artifact_version"; then
    echo "error: failed to upload the file"
    exit 1
  fi
}

function is_gcloud_authenticated() {
    # Checks if gcloud has an active authenticated account.
    # Returns the active account email if authentication exists, otherwise returns empty.
    local account
    account=$(gcloud auth list --filter=status:ACTIVE --format="value(account)" 2>/dev/null)
    echo "$account"
}

function authenticate_gcloud() {
    # Authenticates gcloud **only if necessary**.
    # - If already authenticated, do nothing.
    # - If GOOGLE_APPLICATION_CREDENTIALS is set, use it to authenticate.
    # - Otherwise, assume the CI/CD environment (GitHub/GitLab) has already authenticated externally.
    local auth_email
    auth_email=$(is_gcloud_authenticated)

    if [[ -n "$auth_email" ]]; then
        echo "info: gcloud is already authenticated with $auth_email"
        return 0  # Skip authentication
    fi

    echo "info: gcloud is not authenticated. Authenticating..."

    if [[ -n "$GOOGLE_APPLICATION_CREDENTIALS" ]]; then
        echo "info: Using GOOGLE_APPLICATION_CREDENTIALS: $GOOGLE_APPLICATION_CREDENTIALS"
        if gcloud auth activate-service-account --key-file="$GOOGLE_APPLICATION_CREDENTIALS"; then
            echo "info: gcloud authentication successful."
        else
            echo "error: Failed to authenticate gcloud."
            return 1
        fi
    else
        echo "warning: No GOOGLE_APPLICATION_CREDENTIALS found. Assuming external authentication is already configured."
    fi
}
# The build timestamp, to the millisecond, on any platform.
#
# `date +%3N` is a GNU extension. BSD date has no %N at all, so on macOS it emits the digit
# and the letter literally and every stamp built on a laptop reads ".3N" where the
# milliseconds should be. Python is already required by these scripts - they call
# formatters.py - so it is what is portable here.
function build_timestamp() {
  python3 -c 'import datetime
now = datetime.datetime.now(datetime.timezone.utc)
print(now.strftime("%Y-%m-%d %H:%M:%S.") + f"{now.microsecond // 1000:03d} UTC")'
}

# Fill in a version.json template, leaving nothing beside it.
#
# One copy, because the two build scripts had one each and both had the same two defects.
#
# Substitutes in a single pass to a temporary file rather than with `sed -i -e`. BSD sed reads
# the argument after -i as a backup suffix, so -e became the suffix and every run wrote a
# `version.json-e` next to the file. That file was created inside the build output, so it was
# tarred with it, unpacked, copied into the bucket directory and published - carrying whatever
# the file looked like before the last of the four substitutions, which is to say with
# ###GITHUB_SHA### where the commit should be. It was readable on the public internet.
#
# The placeholder check at the end is the part that would have caught it. A version stamp that
# still contains a placeholder is not a version stamp, and it must not be shipped quietly.
function write_version_json() {
  local _version_json_filename=$1
  local _git_branch_tag_name=$2
  local _git_commit_sha=$3
  local _build_run=$4
  local _directory
  _directory=$(dirname "${_version_json_filename}")
  local _temporary="${_version_json_filename}.writing"

  # What was here before. The backend build leaves a `.bak` of its own beside the file and
  # restores it on exit, so the thing to check is not "is this directory clean" but "did
  # writing the stamp add anything to it".
  local _before
  _before=$(ls -A "${_directory}")

  echo "info: setting the version info in $_version_json_filename"
  sed -e "s|###date###|$(build_timestamp)|g" \
      -e "s|###GITHUB_REF_NAME###|${_git_branch_tag_name}|g" \
      -e "s|###GITHUB_RUN_NUMBER###|${_build_run}|g" \
      -e "s|###GITHUB_SHA###|${_git_commit_sha}|g" \
      "${_version_json_filename}" > "${_temporary}"
  mv "${_temporary}" "${_version_json_filename}"

  if grep -q '###' "${_version_json_filename}"; then
    echo "error: $_version_json_filename still contains a placeholder after substitution:"
    grep -n '###' "${_version_json_filename}"
    exit 1
  fi

  local _added
  _added=$(comm -13 <(echo "$_before" | sort) <(ls -A "${_directory}" | sort))
  if [ -n "$_added" ]; then
    echo "error: writing the version stamp created files beside it, and for the frontend"
    echo "       build this directory is tarred, unpacked and published as it stands:"
    echo "$_added"
    exit 1
  fi

  cat "$_version_json_filename"
}
