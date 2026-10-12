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

        archive = os.path.join(root, branding_archive_name("myrealm.prod"))
        pack_assets(assets, archive)

        unpacked = unpacked_assets_dir(root, "myrealm.prod")
        unpack_assets(archive, unpacked)

        bundle = os.path.join(root, "bundle")
        _write(os.path.join(bundle, "logo.svg"), b"<svg>shipped</svg>")
        _write(os.path.join(bundle, "index.html"), b"<html/>")

        applied = apply_assets(iac_folder=root, stack_name="myrealm.prod", artifacts_dir=bundle)

        assert applied == 2, f"expected two files applied, got {applied}"
        assert open(os.path.join(bundle, "logo.svg"), "rb").read() == b"<svg>mine</svg>", (
            "the operator's logo did not replace the one that shipped")
        assert os.path.exists(os.path.join(bundle, "icons", "favicon.svg")), (
            "a nested asset did not survive the round trip")
        assert os.path.exists(os.path.join(bundle, "index.html")), (
            "applying assets removed part of the bundle")


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
