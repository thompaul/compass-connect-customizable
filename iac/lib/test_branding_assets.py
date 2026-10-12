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
