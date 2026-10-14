"""
A deployment's own asset files, carried from the operator's configuration directory into the
browser bundle.

Branding values - the name, the colours, the URLs - travel as environment variables and have
done for some time. The files those URLs point at did not travel at all. `FRONTEND_LOGO_URL`
is resolved against the deployment's own bucket, and the only way to get a file into that
bucket was to commit it to `frontend-new/public/` in Tabiya's repository, which is exactly
what this phase exists to stop. Every partner so far did it that way, because there was no
other way.

The files now take the same road as the rest of the configuration:

    config-dir/assets/      an operator's directory, beside their .env and stack config
      -> setup_env.py       tars it and uploads it to the realm's generic repository
      -> prepare.py         downloads and unpacks it
      -> prepare_frontend   copies it over the downloaded bundle, before the bucket upload

The generic repository was chosen because it is already where the frontend bundle and the
templates come from, it lives in the realm's own project, and it is torn down with the realm.
Nothing new is created, and nothing new has to be destroyed.

Assets are versioned with the artifacts, like the environment file in Secret Manager: a
deployment pinned to a version gets the branding that was uploaded for it.

One subdirectory is special. Everything in `assets/` replaces a file in the bundle by name -
a logo, an illustration - and the interface reaches it through a URL an operator configured.
`assets/content/` holds the documents the interface *reads*: the privacy policy, the terms of
use, the FAQ. Nothing configures a URL for those, so the deployment has to say which ones it
has, which is what `content_documents` works out and `prepare_frontend` writes into `env.js`.

It is worked out from the files rather than declared beside them on purpose. A list an
operator maintains by hand next to the files it describes is a list that goes stale, and the
failure is invisible: a privacy policy that was uploaded and never shown.
"""
import os
import re
import shutil
import subprocess
import tarfile
from typing import Optional

#: The directory an operator puts their files in, inside the configuration directory they
#: already hand to setup_env.py.
ASSETS_DIRECTORY_NAME = "assets"

#: Anything larger is a mistake rather than a logo. The whole archive rides through an
#: artifact repository and ends up in every page load's bucket, and the failure mode of
#: finding out later is a slow site rather than an error.
MAX_ARCHIVE_BYTES = 25 * 1024 * 1024

#: What a browser can be served. The bundle is public static content, so an operator dropping
#: a spreadsheet, a key or a database export in here would publish it.
ALLOWED_SUFFIXES = {
    ".svg", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".avif", ".ico",
    ".woff", ".woff2", ".ttf", ".otf",
    ".md", ".txt", ".json", ".webmanifest",
}

#: Inside the assets directory: the documents the interface reads rather than links to.
CONTENT_DIRECTORY_NAME = "content"

#: What a document may be called. The kind is the stem and the locale is an optional middle
#: part, so `privacy-policy.md` serves every language and `privacy-policy.sw-KE.md` serves one.
#:
#: Matched strictly, and a file that does not match is an error rather than a file that is
#: ignored. `privacy_policy.md` with an underscore would be uploaded, served, and never
#: looked for - an operator would see the "not configured" page with their document sitting
#: in the bucket a URL away, and nothing anywhere would say why.
CONTENT_DOCUMENT_KINDS = ("privacy-policy", "terms-of-use", "faq")
CONTENT_DOCUMENT_NAME = re.compile(
    r"^(?P<kind>" + "|".join(CONTENT_DOCUMENT_KINDS) + r")(?:\.(?P<locale>[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*))?\.md$")


def branding_archive_name(stack_name: str) -> str:
    """One archive per environment, so a realm's environments can be branded differently."""
    return f"branding-{stack_name}.tar.gz"


def unpacked_assets_dir(iac_folder: str, stack_name: str) -> str:
    """
    Where `prepare.py` leaves the unpacked files for the preparation scripts to find.

    Defined here rather than in either script so the two cannot drift apart: a writer and a
    reader agreeing on a path by coincidence is a bug that only appears in a real deployment.
    """
    return os.path.join(iac_folder, "scripts", "_tmp", "branding", stack_name)


def collect_assets(assets_dir: str) -> list:
    """
    Every file an operator has supplied, checked before it can reach a public bucket.

    Raises rather than skipping. A logo silently left out of a deployment looks exactly like
    a logo that was never configured, which is the class of fault this stage exists to remove.
    """
    collected = []
    for directory, subdirectories, files in os.walk(assets_dir):
        subdirectories[:] = [d for d in subdirectories if not d.startswith(".")]
        for filename in sorted(files):
            if filename.startswith("."):
                continue
            path = os.path.join(directory, filename)
            if os.path.islink(path):
                raise ValueError(
                    f"{os.path.relpath(path, assets_dir)} is a symbolic link. Assets are "
                    f"uploaded and served as files; put the file itself here.")
            suffix = os.path.splitext(filename)[1].lower()
            if suffix not in ALLOWED_SUFFIXES:
                raise ValueError(
                    f"{os.path.relpath(path, assets_dir)} has an extension this deployment "
                    f"will not publish ({suffix or 'none'}). These files are served to every "
                    f"visitor; allowed: {', '.join(sorted(ALLOWED_SUFFIXES))}.")
            collected.append(path)
    return collected


def pack_assets(assets_dir: str, archive_path: str) -> int:
    """Tar an operator's assets directory, returning the archive size in bytes."""
    files = collect_assets(assets_dir)
    if not files:
        raise ValueError(f"{assets_dir} contains no files to upload.")

    with tarfile.open(archive_path, "w:gz") as archive:
        for path in files:
            archive.add(path, arcname=os.path.relpath(path, assets_dir))

    size = os.path.getsize(archive_path)
    if size > MAX_ARCHIVE_BYTES:
        os.remove(archive_path)
        raise ValueError(
            f"The assets archive is {size / 1024 / 1024:.1f} MB, over the "
            f"{MAX_ARCHIVE_BYTES / 1024 / 1024:.0f} MB limit. These files are downloaded on "
            f"every deployment and served on every page load.")
    return size


def unpack_assets(archive_path: str, destination_dir: str) -> None:
    """Unpack a downloaded archive, refusing any member that would escape the destination."""
    if os.path.exists(destination_dir):
        shutil.rmtree(destination_dir)
    os.makedirs(destination_dir, exist_ok=True)

    with tarfile.open(archive_path, "r:gz") as archive:
        for member in archive.getmembers():
            if member.issym() or member.islnk():
                raise ValueError(f"The assets archive contains a link: {member.name}")
            target = os.path.realpath(os.path.join(destination_dir, member.name))
            if not target.startswith(os.path.realpath(destination_dir) + os.sep):
                raise ValueError(f"The assets archive contains a path outside it: {member.name}")
        # The checks above are the ones that hold on the interpreter deployments actually run:
        # 3.11 ships `data_filter` but still defaults `extraction_filter` to None, which is the
        # old permissive behaviour. `filter="data"` is belt and braces, and silences the
        # deprecation warning on the versions in between.
        archive.extractall(destination_dir, filter="data")


def apply_assets(*, iac_folder: str, stack_name: str, artifacts_dir: str) -> Optional[int]:
    """
    Copy a deployment's own files over the downloaded bundle.

    Returns the number of files applied, or None when this deployment supplied none - which
    is an ordinary thing to do, and leaves it showing the product's own marks.

    The copy is one-way and last: an operator's file of the same name wins over the one that
    shipped, which is how a deployment replaces an illustration rather than only adding to it.
    """
    source = unpacked_assets_dir(iac_folder, stack_name)
    if not os.path.isdir(source):
        # Said out loud. The difference between "this deployment supplied no assets" and
        # "the assets were put somewhere this did not look" is invisible in the result -
        # both leave the product's own marks in place - so the log has to carry it.
        print(f"info: no assets supplied for {stack_name} ({source} is not there); "
              f"the bundle keeps the marks that shipped with it")
        return None

    applied = 0
    for directory, _, files in os.walk(source):
        relative = os.path.relpath(directory, source)
        target_dir = artifacts_dir if relative == "." else os.path.join(artifacts_dir, relative)
        os.makedirs(target_dir, exist_ok=True)
        for filename in files:
            shutil.copy2(os.path.join(directory, filename), os.path.join(target_dir, filename))
            applied += 1

    print(f"info: applied {applied} asset file(s) supplied by this deployment")
    return applied


def content_documents(*, bundle_dir: str, supported_locales: Optional[list] = None) -> list:
    """
    The documents this deployment supplies, as the browser will have to ask for them.

    Read from the prepared bundle rather than from the operator's directory, so what is
    reported is what will actually be served: a file the operator put there and a file the
    product shipped are indistinguishable by the time this runs, which is correct, because
    they are indistinguishable to the browser too.

    Raises on a file it cannot account for. A misnamed document is the quietest failure in
    this whole path - it uploads, it is served, and nothing ever asks for it - so it is the
    one worth refusing a deployment over.
    """
    content_dir = os.path.join(bundle_dir, CONTENT_DIRECTORY_NAME)
    if not os.path.isdir(content_dir):
        return []

    documents = []
    for entry in sorted(os.listdir(content_dir)):
        if entry.startswith("."):
            continue
        if os.path.isdir(os.path.join(content_dir, entry)):
            raise ValueError(
                f"{CONTENT_DIRECTORY_NAME}/{entry} is a directory. Documents are looked up by "
                f"name, so they all sit directly in {CONTENT_DIRECTORY_NAME}/.")

        match = CONTENT_DOCUMENT_NAME.match(entry)
        if not match:
            raise ValueError(
                f"{CONTENT_DIRECTORY_NAME}/{entry} is not a name this deployment will ever ask "
                f"for, so it would be published and never shown. Documents are named "
                f"<kind>.md or <kind>.<locale>.md, where <kind> is one of: "
                f"{', '.join(CONTENT_DOCUMENT_KINDS)}.")

        locale = match.group("locale")
        if locale and supported_locales is not None and locale not in supported_locales:
            raise ValueError(
                f"{CONTENT_DIRECTORY_NAME}/{entry} is written for '{locale}', which this "
                f"deployment does not offer ({', '.join(supported_locales) or 'no locales'}). "
                f"Nobody could select the language it is in.")

        documents.append(entry)

    return documents


def generic_artifacts_file_exists(*, repository: dict, file_name: str, version: str) -> bool:
    """
    Whether this file is in the repository at this version.

    Asked, rather than inferred from a failure. The caller used to learn that a deployment had
    supplied no assets from a non-zero exit code out of `gcloud artifacts files download` - and
    a non-zero exit is also what a permission failure, a network failure, and a refusal to
    overwrite a file already on disk all look like. The last of those happened on every
    deployment after the first, and was reported as "this deployment supplied none" while the
    previous deployment's files were served in its place.

    A failure here is left to propagate. Not being able to ask is not the same as the answer
    being no.
    """
    listed = subprocess.run(
        ["gcloud", "artifacts", "files", "list",
         f'--repository={repository["name"]}',
         f'--location={repository["location"]}',
         f'--project={repository["project"]}',
         "--package=artifacts", f"--version={version}",
         "--format=value(name)", f"--filter=name:{file_name}"],
        check=True, capture_output=True, text=True)
    return bool(listed.stdout.strip())


def fetch_deployment_assets(*, repository: dict, version: str, archive_name: str,
                            download_dir: str, unpacked_dir: str, download,
                            exists=generic_artifacts_file_exists) -> bool:
    """
    Put this deployment's own asset files on disk, and nothing else.

    Returns whether this deployment supplied any. Supplying none is ordinary and not an
    error - it leaves the product's own marks in place - so it is reported rather than
    raised.

    Both directories are emptied before anything else happens, which is the whole point of
    the function. They have the same paths on every deployment of a given environment, so
    whatever is in them belongs to the deployment before this one, and every later step here
    can fail. A deployment that stops half way through must not leave a previous
    configuration's logos and documents behind for the next command to pick up and publish
    under this one's name.

    `download` is passed in rather than imported: the real one lives in a module that pulls
    in pulumi, and this one is deliberately standard library only, so that the two
    preparation scripts and the tests can all use it.
    """
    for directory in (download_dir, unpacked_dir):
        if os.path.exists(directory):
            shutil.rmtree(directory)
    os.makedirs(download_dir, exist_ok=True)

    if not exists(repository=repository, file_name=archive_name, version=version):
        return False

    # Deliberately not guarded. Past this point the archive is known to be there, so every
    # way the download can still fail is a reason to stop the deployment rather than a
    # reason to go on and serve somebody else's branding.
    download(repository=repository, output_dir=download_dir, version=version,
             file_name=archive_name)
    unpack_assets(os.path.join(download_dir, archive_name), unpacked_dir)
    return True


def upload_generic_artifacts_file(*, repository: dict, file_path: str, version: str) -> None:
    """
    Put a file in the realm's generic repository, replacing what is there at that version.

    Mirrors `iac/scripts/common.sh:upload_file`, which the build pipeline uses for the same
    repository: delete first, because a generic upload will not overwrite in place.
    """
    file_name = os.path.basename(file_path)
    common = [
        f'--repository={repository["name"]}',
        f'--location={repository["location"]}',
        f'--project={repository["project"]}',
    ]

    existing = subprocess.run(
        ["gcloud", "artifacts", "files", "list", *common, "--package=artifacts",
         f"--version={version}", "--format=value(name)", f"--filter=name:{file_name}"],
        check=False, capture_output=True, text=True).stdout.strip()

    if existing:
        print(f"info: replacing the existing {file_name} at {version}")
        subprocess.run(
            ["gcloud", "artifacts", "files", "delete", f"artifacts:{version}:{file_name}",
             *common, "--quiet"], check=True, text=True)

    subprocess.run(
        ["gcloud", "artifacts", "generic", "upload", "--package=artifacts", *common,
         f"--source={file_path}", f"--version={version}"], check=True, text=True)
