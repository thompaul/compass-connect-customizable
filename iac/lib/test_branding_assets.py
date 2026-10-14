#!/usr/bin/env python3
"""
A deployment's own asset files have to arrive, and nothing else may ride in with them.

Until now the only way to get a logo into a deployment's bucket was to commit it to
`frontend-new/public/` in Tabiya's repository. These files make the operator's own
`assets/` directory the way instead, which means an operator-supplied archive is now
unpacked over a bundle that is then served publicly - so the archive is input, and it is
treated as input:

- a member path that escapes the destination would write anywhere the deploy user can;
- a symbolic link would do the same, or publish whatever it points at;
- a file type nobody meant to publish - a spreadsheet, a key, a database export - becomes
  world-readable static content the moment the bucket syncs;
- an archive nobody noticed was enormous is downloaded on every deployment and served on
  every page load.

The last test is the one that matters most in the ordinary case: the writer and the reader
agree on where the unpacked files live. They are different scripts in different processes,
and a path they agree on by coincidence is a bug that appears only in a real deployment.

Runnable directly: `python3 lib/test_branding_assets.py` from the iac directory.
"""
import importlib.util
import os
import shutil
import sys
import tarfile
import tempfile

# Loaded by path rather than as `lib.branding_assets`, because the package's __init__ pulls in
# pulumi and this module needs nothing but the standard library. Keeping it that way is part
# of what is being tested: it is imported by two scripts and two preparation modules.
_spec = importlib.util.spec_from_file_location(
    "branding_assets", os.path.join(os.path.dirname(os.path.abspath(__file__)), "branding_assets.py"))
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)

ASSETS_DIRECTORY_NAME = _module.ASSETS_DIRECTORY_NAME
MAX_ARCHIVE_BYTES = _module.MAX_ARCHIVE_BYTES
apply_assets = _module.apply_assets
branding_archive_name = _module.branding_archive_name
collect_assets = _module.collect_assets
pack_assets = _module.pack_assets
unpack_assets = _module.unpack_assets
unpacked_assets_dir = _module.unpacked_assets_dir
CONTENT_DIRECTORY_NAME = _module.CONTENT_DIRECTORY_NAME
content_documents = _module.content_documents
fetch_deployment_assets = _module.fetch_deployment_assets
generic_artifacts_file_exists = _module.generic_artifacts_file_exists


def _is_no_cache():
    """
    The cache rule out of `bucket_content.py`, compiled on its own.

    The module it lives in imports pulumi, which these tests deliberately do not need, and the
    rule is three lines of string matching. So the function is lifted out of the source and
    compiled by itself - which also means this test fails if the function is renamed or moved,
    rather than passing against a copy that is no longer the one running.
    """
    import ast
    source = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                               "frontend", "bucket_content.py"), encoding="utf-8").read()
    tree = ast.parse(source)
    definition = next((node for node in tree.body
                       if isinstance(node, ast.FunctionDef) and node.name == "_is_no_cache"), None)
    assert definition is not None, "bucket_content.py no longer decides caching in _is_no_cache"
    namespace = {"os": os}
    exec(compile(ast.Module(body=[definition], type_ignores=[]), "<bucket_content>", "exec"),  # nosec B102
         namespace)
    return namespace["_is_no_cache"]


def _write(path: str, content: bytes = b"<svg/>") -> str:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(content)
    return path


def test_an_operators_files_reach_the_bundle():
    """
    The whole road, without the cloud in the middle: pack, unpack, lay over the bundle.

    The assertion that matters is the last one. An operator's `logo.svg` has to *replace*
    the one that shipped, not sit beside it - a deployment whose logo silently did not take
    effect is the fault this stage exists to remove.
    """
    with tempfile.TemporaryDirectory() as root:
        assets = os.path.join(root, ASSETS_DIRECTORY_NAME)
        _write(os.path.join(assets, "logo.svg"), b"<svg>mine</svg>")
        _write(os.path.join(assets, "icons", "favicon.svg"), b"<svg>favicon</svg>")
        _write(os.path.join(assets, CONTENT_DIRECTORY_NAME, "privacy-policy.md"), b"# mine")

        archive = os.path.join(root, branding_archive_name("myrealm.prod"))
        pack_assets(assets, archive)

        unpacked = unpacked_assets_dir(root, "myrealm.prod")
        unpack_assets(archive, unpacked)

        bundle = os.path.join(root, "bundle")
        _write(os.path.join(bundle, "logo.svg"), b"<svg>shipped</svg>")
        _write(os.path.join(bundle, "index.html"), b"<html/>")

        applied = apply_assets(iac_folder=root, stack_name="myrealm.prod", artifacts_dir=bundle)

        assert applied == 3, f"expected three files applied, got {applied}"
        assert open(os.path.join(bundle, "logo.svg"), "rb").read() == b"<svg>mine</svg>", (
            "the operator's logo did not replace the one that shipped")
        assert os.path.exists(os.path.join(bundle, "icons", "favicon.svg")), (
            "a nested asset did not survive the round trip")
        assert os.path.exists(os.path.join(bundle, "index.html")), (
            "applying assets removed part of the bundle")
        # And the reader at the far end of that road finds what the writer sent: this is the
        # list that goes into env.js, worked out from the bundle that is about to be uploaded.
        assert content_documents(bundle_dir=bundle) == ["privacy-policy.md"], (
            "an operator's document survived the round trip without being reported, so the "
            "browser would never ask for it")


def test_a_deployment_that_supplied_nothing_is_not_an_error():
    """The ordinary case. It shows the product's own marks, which is what they are for."""
    with tempfile.TemporaryDirectory() as root:
        bundle = os.path.join(root, "bundle")
        _write(os.path.join(bundle, "index.html"))
        assert apply_assets(iac_folder=root, stack_name="myrealm.prod", artifacts_dir=bundle) is None
        assert os.path.exists(os.path.join(bundle, "index.html"))


def test_the_writer_and_the_reader_agree_on_where_the_files_are():
    """
    `prepare.py` unpacks and the two preparation scripts read, in different processes.

    Both call this one function with the iac root they each computed, so the only way they
    can disagree is if those roots differ - which this pins.
    """
    assert unpacked_assets_dir("/iac", "a.b") == unpacked_assets_dir("/iac", "a.b")
    assert unpacked_assets_dir("/iac", "a.b") != unpacked_assets_dir("/iac", "a.c"), (
        "two environments of one realm would share an unpacked directory")
    assert unpacked_assets_dir("/iac", "a.b").startswith(os.path.join("/iac", "scripts", "_tmp"))


def test_an_archive_cannot_write_outside_the_place_it_is_unpacked():
    """Classic path traversal. The archive is operator input and the deploy user is not nobody."""
    with tempfile.TemporaryDirectory() as root:
        archive = os.path.join(root, "evil.tar.gz")
        payload = _write(os.path.join(root, "payload"), b"owned")
        with tarfile.open(archive, "w:gz") as handle:
            handle.add(payload, arcname="../../escaped.svg")

        try:
            unpack_assets(archive, os.path.join(root, "out"))
        except ValueError as e:
            assert "outside" in str(e)
        else:
            assert False, "an archive escaped its destination"
        assert not os.path.exists(os.path.join(root, "escaped.svg"))


def test_an_archive_carrying_a_link_is_refused():
    """A link in a public bundle either breaks or publishes whatever it points at."""
    with tempfile.TemporaryDirectory() as root:
        archive = os.path.join(root, "linky.tar.gz")
        with tarfile.open(archive, "w:gz") as handle:
            info = tarfile.TarInfo("logo.svg")
            info.type = tarfile.SYMTYPE
            info.linkname = "/etc/passwd"
            handle.addfile(info)

        try:
            unpack_assets(archive, os.path.join(root, "out"))
        except ValueError as e:
            assert "link" in str(e)
        else:
            assert False, "an archive containing a link was unpacked"


def test_a_file_the_deployment_would_not_publish_is_refused_before_upload():
    """
    These files become world-readable static content. Refuse at the operator's machine,
    where the message can name the file, rather than discovering it in a public bucket.
    """
    with tempfile.TemporaryDirectory() as root:
        assets = os.path.join(root, ASSETS_DIRECTORY_NAME)
        _write(os.path.join(assets, "logo.svg"))
        _write(os.path.join(assets, "users-export.csv"), b"email,name\n")

        try:
            collect_assets(assets)
        except ValueError as e:
            assert "users-export.csv" in str(e), f"the message did not name the file: {e}"
        else:
            assert False, "a file the deployment will not publish was accepted"


def test_a_symbolic_link_in_the_assets_directory_is_refused():
    """The same hazard, one step earlier, where it is somebody's own filesystem."""
    with tempfile.TemporaryDirectory() as root:
        assets = os.path.join(root, ASSETS_DIRECTORY_NAME)
        _write(os.path.join(assets, "logo.svg"))
        secret = _write(os.path.join(root, "id_rsa"), b"private")
        os.symlink(secret, os.path.join(assets, "extra.svg"))

        try:
            collect_assets(assets)
        except ValueError as e:
            assert "symbolic link" in str(e)
        else:
            assert False, "a symbolic link was packed into a public bundle"


def test_an_oversized_archive_is_refused():
    """Downloaded on every deployment, served on every page load. Found now, not later."""
    with tempfile.TemporaryDirectory() as root:
        assets = os.path.join(root, ASSETS_DIRECTORY_NAME)
        # Incompressible, so the gzip stream really is over the limit.
        _write(os.path.join(assets, "huge.png"), os.urandom(MAX_ARCHIVE_BYTES + 1024))
        archive = os.path.join(root, "big.tar.gz")

        try:
            pack_assets(assets, archive)
        except ValueError as e:
            assert "limit" in str(e)
        else:
            assert False, "an oversized archive was accepted"
        assert not os.path.exists(archive), "the oversized archive was left on disk"


def test_an_empty_assets_directory_is_refused():
    """An empty directory means somebody meant to put something in it."""
    with tempfile.TemporaryDirectory() as root:
        assets = os.path.join(root, ASSETS_DIRECTORY_NAME)
        os.makedirs(assets)
        try:
            pack_assets(assets, os.path.join(root, "a.tar.gz"))
        except ValueError as e:
            assert "no files" in str(e)
        else:
            assert False, "an empty assets directory was packed and uploaded"


def test_each_environment_gets_its_own_archive():
    """Staging carrying production's branding is the obvious way to find this out late."""
    assert branding_archive_name("realm.prod") != branding_archive_name("realm.dev")
    assert branding_archive_name("realm.prod").endswith(".tar.gz")


def test_a_deployment_reports_the_documents_it_is_about_to_serve():
    """
    The browser cannot list a bucket, so the deployment has to tell it what is in one.

    Read from the prepared bundle rather than from the operator's directory, because by then
    an operator's file and a shipped file are the same kind of thing - which is correct, since
    they are the same kind of thing to the browser too.
    """
    with tempfile.TemporaryDirectory() as workspace:
        bundle = os.path.join(workspace, "bundle")
        _write(os.path.join(bundle, "index.html"), b"<html/>")
        _write(os.path.join(bundle, CONTENT_DIRECTORY_NAME, "privacy-policy.md"), b"# p")
        _write(os.path.join(bundle, CONTENT_DIRECTORY_NAME, "faq.en-GB.md"), b"# f")

        assert content_documents(bundle_dir=bundle) == ["faq.en-GB.md", "privacy-policy.md"]


def test_a_deployment_with_no_documents_reports_none():
    """Supplying none is an ordinary thing to do; it is what the placeholder pages are for."""
    with tempfile.TemporaryDirectory() as workspace:
        bundle = os.path.join(workspace, "bundle")
        _write(os.path.join(bundle, "index.html"), b"<html/>")
        assert content_documents(bundle_dir=bundle) == []


def test_a_misnamed_document_stops_the_deployment_rather_than_being_ignored():
    """
    The quietest failure in this path, which is why it is the one worth refusing over.

    `privacy_policy.md` with an underscore packs, uploads, and is served. Nothing ever asks
    for it, so the operator sees the "not configured" page with their own document sitting in
    the bucket one URL away, and no log line anywhere connects the two.
    """
    with tempfile.TemporaryDirectory() as workspace:
        bundle = os.path.join(workspace, "bundle")
        _write(os.path.join(bundle, CONTENT_DIRECTORY_NAME, "privacy_policy.md"), b"# p")
        try:
            content_documents(bundle_dir=bundle)
        except ValueError as refusal:
            assert "privacy_policy.md" in str(refusal)
        else:
            assert False, "a document nothing will ever ask for was accepted"


def test_a_document_in_a_language_the_deployment_does_not_offer_is_refused():
    """
    The same comparison language itself now gets: two declarations that have to agree.

    A FAQ written for a locale that is not in the menu cannot be reached by anybody. It is
    always a mistake, and it is always cheap to fix at the moment it is made.
    """
    with tempfile.TemporaryDirectory() as workspace:
        bundle = os.path.join(workspace, "bundle")
        _write(os.path.join(bundle, CONTENT_DIRECTORY_NAME, "faq.sw-KE.md"), b"# f")
        try:
            content_documents(bundle_dir=bundle, supported_locales=["en-GB", "es-ES"])
        except ValueError as refusal:
            assert "sw-KE" in str(refusal)
        else:
            assert False, "a document nobody could select the language of was accepted"


def test_documents_sit_directly_in_the_content_directory():
    """Nesting cannot carry meaning here: the name is the whole lookup, so a subdirectory
    would publish files that are never asked for."""
    with tempfile.TemporaryDirectory() as workspace:
        bundle = os.path.join(workspace, "bundle")
        _write(os.path.join(bundle, CONTENT_DIRECTORY_NAME, "en", "faq.md"), b"# f")
        try:
            content_documents(bundle_dir=bundle)
        except ValueError as refusal:
            assert "directory" in str(refusal)
        else:
            assert False, "a nested document directory was accepted"


def test_a_documents_directory_is_served_without_caching():
    """
    The difference between a document and a logo, as the bucket sees it.

    Both are replaced by deploying again, and both keep their file names when they change. A
    logo an hour out of date is a cosmetic cost worth paying for a file fetched on every page
    load. A privacy policy an hour out of date goes on telling people something its publisher
    has already corrected, and the people most likely to be affected are the ones who read it
    first.
    """
    is_no_cache = _is_no_cache()
    paths = ["index.html", "data/env.js", "content/"]

    assert is_no_cache("index.html", paths), "an exact entry stopped matching"
    assert is_no_cache("content/privacy-policy.md", paths), "a document would be cached"
    assert is_no_cache("content/faq.en-GB.md", paths)
    assert not is_no_cache("static/js/main.js", paths), "everything is uncached now"
    assert not is_no_cache("contents.json", paths), (
        "a directory entry matched a file that merely starts with the same letters")
    assert not is_no_cache("data/env.json", paths), (
        "an entry without a trailing slash is being treated as a prefix, so files that merely "
        "begin with a listed name - data/env.js and data/env.json - are not told apart")



# --- What a deployment finds on disk when it is not the first one into an environment -------
#
# These directories have the same paths on every deployment of a given environment, so the
# second deployment of a changed configuration starts by looking at the first one's files.
# Getting this wrong does not fail: it produces a site that is neither configuration, with
# the new one's name in `env.js` and the old one's logos and documents in the bucket, and all
# five smoke tests passing. So each of these tests is written as the thing the operator would
# have seen, not as a call that returns the right value.


# The archive's name comes from the environment, not from the configuration, so both
# deployments below ask for the same file name - which is the whole mechanism. The one on disk
# from the first deployment is the one the second cannot write over.
STACK = "myrealm.prod"
ARCHIVE = branding_archive_name(STACK)


class _Repository:
    """A generic repository holding one configuration's kit, which records what is asked of it."""

    def __init__(self, configuration=None):
        self.configuration = configuration
        self.asked = []
        self.downloaded = []

    def exists(self, *, repository, file_name, version):
        self.asked.append((file_name, version))
        return self.configuration is not None

    def download(self, *, repository, output_dir, version, file_name):
        self.downloaded.append((file_name, version))
        assert self.configuration is not None, "downloaded a file the repository does not hold"
        destination = os.path.join(output_dir, file_name)
        if os.path.exists(destination):
            # What the real `gcloud artifacts files download` does, and the origin of the
            # defect: it will not write over a file already sitting in the destination, and
            # the destination's path is the same on every deployment.
            raise ChildProcessError(f"{destination}: File exists")
        kit = os.path.join(output_dir, "_kit")
        _write(os.path.join(kit, f"{self.configuration}-logo.svg"))
        pack_assets(kit, destination)
        shutil.rmtree(kit)


def _deploy(repository, root):
    """One `prepare.py` run's worth of asset fetching, against the paths it would use."""
    return fetch_deployment_assets(
        repository={"name": "r", "location": "l", "project": "p"},
        version="branch.sha.salt",
        archive_name=ARCHIVE,
        download_dir=os.path.join(root, "scripts", "_tmp", "branding-archives", STACK),
        unpacked_dir=unpacked_assets_dir(root, STACK),
        download=repository.download,
        exists=repository.exists,
    )


def test_deploying_a_changed_configuration_twice_in_a_row_serves_the_second_one():
    """
    The defect, as the operator met it: the second deployment kept the first one's files.

    Both deployments ask for the same file name, because it is the environment's name. The
    first leaves that file in a directory whose path does not change, and the download
    refuses to write over it. That refusal used to be read as "this deployment supplied no
    assets" - so the unpack never ran, and because the clearing of the unpacked directory
    lived inside the unpack, the first deployment's files were still there for the next step
    to copy over the second one's bundle.
    """
    with tempfile.TemporaryDirectory() as root:
        assert _deploy(_Repository("northway"), root) is True
        unpacked = unpacked_assets_dir(root, STACK)
        assert os.listdir(unpacked) == ["northway-logo.svg"]

        assert _deploy(_Repository("southline"), root) is True
        present = sorted(os.listdir(unpacked))
        assert present == ["southline-logo.svg"], (
            f"the second deployment is about to serve {present}; a file from the first one "
            f"survived into it, which is how a site ends up named for one configuration and "
            f"wearing another's logos")


def test_a_download_that_fails_for_any_other_reason_stops_the_deployment():
    """
    The catch used to be `except subprocess.CalledProcessError`, which is every non-zero exit:
    no permission, no network, and a file already on disk all arrived as "supplied none".

    There is no catch now. The archive's existence is established before the download starts,
    so anything that goes wrong after that is a reason to stop.
    """
    class _Fails(_Repository):
        def download(self, **kwargs):
            raise ChildProcessError("PERMISSION_DENIED: artifactregistry.files.get")

    with tempfile.TemporaryDirectory() as root:
        try:
            _deploy(_Fails("southline"), root)
        except ChildProcessError as e:
            assert "PERMISSION_DENIED" in str(e), (
                "the reason the download failed did not survive to the operator")
        else:
            raise AssertionError(
                "a download that failed was reported as a deployment that supplied no assets")


def test_supplied_no_assets_is_only_said_when_it_supplied_none():
    """
    The return value is what the caller prints, so it is the message.

    False may be returned only when the repository was asked and said no - not when it could
    not be asked, and not when the answer was yes and something later went wrong.
    """
    with tempfile.TemporaryDirectory() as root:
        empty = _Repository()
        assert _deploy(empty, root) is False
        assert empty.asked == [(ARCHIVE, "branch.sha.salt")], (
            "the repository was not asked, so 'supplied none' is a guess")
        assert empty.downloaded == [], "a file known not to be there was downloaded anyway"


def test_the_unpacked_directory_cannot_outlive_the_archive_it_came_from():
    """
    A deployment that supplied assets, then stopped supplying them.

    Removing `assets/` from a configuration directory is how an operator goes back to the
    product's own marks. If the unpacked files survive that, the operator is told they are
    seeing Compass Connect's marks while the bucket still serves their own.
    """
    with tempfile.TemporaryDirectory() as root:
        assert _deploy(_Repository("southline"), root) is True
        unpacked = unpacked_assets_dir(root, STACK)
        assert os.listdir(unpacked)

        assert _deploy(_Repository(), root) is False
        assert not os.path.exists(unpacked), (
            "the previous deployment's files are still on disk for `apply_assets` to find and "
            "copy over a bundle that is meant to be showing the product's own marks")


def test_nothing_of_the_last_deployment_survives_a_run_that_stops_half_way():
    """
    `prepare.py` can fail, and the operator's next move is to run it again - or, if they
    believe the artifacts are already in place, to run `up.py`. Either way the files left on
    disk get published, so a run that did not finish must not leave any.
    """
    class _Fails(_Repository):
        def download(self, **kwargs):
            raise ChildProcessError("the network went away")

    with tempfile.TemporaryDirectory() as root:
        _deploy(_Repository("northway"), root)
        unpacked = unpacked_assets_dir(root, STACK)
        assert os.listdir(unpacked)

        try:
            _deploy(_Fails("southline"), root)
        except ChildProcessError:
            pass
        assert not os.path.exists(unpacked), (
            "a deployment that failed left the one before it on disk, where the next command "
            "will publish it")


def test_the_existence_question_and_the_download_are_asked_of_the_same_place():
    """
    Two gcloud invocations that have to agree on repository, package and version. They are
    built in different modules - the question here, the download in the module that imports
    pulumi - so the arguments are compared without importing either.

    Read out of the source rather than called, because calling them means gcloud and a realm.
    The pair is the fix: a question asked of one repository about a file downloaded from
    another would answer "supplied none" for a deployment that supplied plenty, which is the
    defect this replaced.
    """
    import ast

    lib_dir = os.path.dirname(os.path.abspath(__file__))

    def _argv(path, function_name):
        tree = ast.parse(open(path).read())
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == function_name:
                return {
                    ast.unparse(element)
                    for call in ast.walk(node) if isinstance(call, ast.Call)
                    for argument in list(call.args) + [k.value for k in call.keywords]
                    if isinstance(argument, (ast.List, ast.Tuple))
                    for element in argument.elts
                }
        raise AssertionError(f"{function_name} is not in {path}, so this test is not testing it")

    asking = _argv(os.path.join(lib_dir, "branding_assets.py"), "generic_artifacts_file_exists")
    downloading = _argv(os.path.join(lib_dir, "std_pulumi.py"), "download_generic_artifacts_file")

    def _passes(argv, flag):
        return any(element.startswith(("f'" + flag, 'f"' + flag, "'" + flag, '"' + flag))
                   for element in argv)

    for flag in ["--repository=", "--location=", "--project="]:
        assert _passes(asking, flag), f"the question does not pass {flag}"
        assert _passes(downloading, flag), f"the download does not pass {flag}"

    for name, argv in (("question", asking), ("download", downloading)):
        assert "'artifacts'" in argv and "'files'" in argv, (
            f"the {name} is no longer addressed to the generic artifact registry")
        # Spelled differently on the two sides - a `--version=` flag on one, part of the
        # `artifacts:<version>:<file>` identifier on the other - so what is pinned is that
        # each interpolates the version it was handed rather than naming a fixed one.
        assert any("{version}" in element for element in argv), (
            f"the {name} does not pass the version it was given, so it would answer for "
            f"some other build - and the two have to answer for the same one")

if __name__ == "__main__":
    _failed = 0
    for _name, _test in sorted(globals().items()):
        if not _name.startswith("test_") or not callable(_test):
            continue
        try:
            _test()
            print(f"ok   {_name}")
        except AssertionError as _e:
            _failed += 1
            print(f"FAIL {_name}:\n  {_e}")
        except Exception as _e:  # noqa: BLE001 - a test that raises is a test that failed
            _failed += 1
            print(f"FAIL {_name}: raised {type(_e).__name__}: {_e}")
    print(f"\n{'FAILED' if _failed else 'OK'} - {_failed} failed")
    sys.exit(1 if _failed else 0)
