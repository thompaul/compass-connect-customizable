#!/usr/bin/env python3
"""
The build must not publish anything it did not mean to, and a date must be a date.

`write_version_json` used two GNU-only idioms, and the deployment path is documented for an
operator on a laptop:

- `sed -i -e` — BSD sed reads the argument after `-i` as the backup suffix, so `-e` became the
  suffix and every run wrote `version.json-e` beside the file. It was created inside the build
  output, so it was tarred with it, unpacked by `prepare.py`, copied into the bucket directory
  and uploaded. It held whatever the file looked like before the last of four substitutions —
  that is, with `###GITHUB_SHA###` where the commit belongs — and it was readable on the public
  internet with a 200.

- `date +%3N` — BSD date has no `%N`, so the digit and the letter came out literally and every
  stamp built on a laptop read `.3N` where the milliseconds should be. `data/version.json` is
  served uncached precisely so an operator can confirm which build is live; its timestamp had
  never been a timestamp on any build not made by CI.

These tests run the real function out of `common.sh` on this machine, which is the only place
the difference shows. Reading the script for the absent idioms is not enough: the point is that
the output is the same here as in CI.

Runnable directly: `python3 scripts/test_version_stamp.py` from the iac directory.
"""
import datetime
import json
import os
import subprocess
import sys
import tempfile

_SCRIPTS = os.path.dirname(os.path.abspath(__file__))
_IAC = os.path.dirname(_SCRIPTS)
_ROOT = os.path.dirname(_IAC)
_COMMON = os.path.join(_SCRIPTS, "common.sh")

TEMPLATES = {
    "backend": os.path.join(_ROOT, "backend", "app", "version", "version.json"),
    "frontend": os.path.join(_ROOT, "frontend-new", "public", "data", "version.json"),
}
SHA = "fc95029324bc5f4bd298560597ef9b7c996de744"
BRANCH = "phase1/08a-dns-shadowing"


def _write_version_json(template: str, directory: str) -> str:
    """Run the real function, in a directory of our own, and return the file it produced."""
    destination = os.path.join(directory, "version.json")
    with open(template) as source, open(destination, "w") as copy:
        copy.write(source.read())
    result = subprocess.run(
        ["bash", "-c",
         f'source "{_COMMON}" >/dev/null 2>&1; '
         f'write_version_json "{destination}" "{BRANCH}" "{SHA}" "7"'],
        capture_output=True, text=True)
    assert result.returncode == 0, (
        f"write_version_json failed:\n{result.stdout}\n{result.stderr}")
    return destination


def test_the_build_leaves_one_file_and_no_others():
    """
    The defect itself. Whatever is in this directory is tarred, unpacked and published, so
    a second file is a second file on the public internet.
    """
    for name, template in TEMPLATES.items():
        with tempfile.TemporaryDirectory() as directory:
            _write_version_json(template, directory)
            present = sorted(os.listdir(directory))
            assert present == ["version.json"], (
                f"the {name} build left {present} behind; everything here reaches the bucket")


def test_the_date_is_a_date():
    for name, template in TEMPLATES.items():
        with tempfile.TemporaryDirectory() as directory:
            stamp = json.load(open(_write_version_json(template, directory)))
            try:
                datetime.datetime.strptime(stamp["date"], "%Y-%m-%d %H:%M:%S.%f UTC")
            except ValueError as e:
                raise AssertionError(
                    f"the {name} stamp's date {stamp['date']!r} is not a date: {e}") from e


def test_the_milliseconds_are_milliseconds():
    """
    Three digits, because that is what `%3N` produces in CI and the two builds have to agree.
    `%f` would give six and `%N` would give nine.
    """
    with tempfile.TemporaryDirectory() as directory:
        stamp = json.load(open(_write_version_json(TEMPLATES["backend"], directory)))
        fraction = stamp["date"].split(".")[1].split()[0]
        assert len(fraction) == 3, (
            f"the fractional second is {fraction!r}, which a build in CI would not produce")
        assert fraction.isdigit(), f"{fraction!r} is not a number of milliseconds"


def test_nothing_is_published_still_asking_to_be_filled_in():
    """
    The live file said `"sha":"###GITHUB_SHA###"`. A stamp whose whole purpose is to say which
    commit is running must not ship saying it does not know.
    """
    for name, template in TEMPLATES.items():
        with tempfile.TemporaryDirectory() as directory:
            written = open(_write_version_json(template, directory)).read()
            assert "###" not in written, (
                f"the {name} stamp still contains a placeholder:\n{written}")


def test_the_backend_builds_own_backup_is_not_mistaken_for_a_stray():
    """
    `build-and-upload-be.sh` copies `version.json` to `version.json.bak` before calling this
    and restores it on exit. A check for "is this directory clean" rather than "did writing
    the stamp add to it" would fail every backend build - which is the check this replaced.
    """
    with tempfile.TemporaryDirectory() as directory:
        with open(TEMPLATES["backend"]) as source:
            template = source.read()
        for name in ("version.json", "version.json.bak"):
            with open(os.path.join(directory, name), "w") as f:
                f.write(template)

        result = subprocess.run(
            ["bash", "-c",
             f'source "{_COMMON}" >/dev/null 2>&1; '
             f'write_version_json "{os.path.join(directory, "version.json")}" '
             f'"{BRANCH}" "{SHA}" "7"'],
            capture_output=True, text=True)
        assert result.returncode == 0, (
            f"a backup the build made on purpose was treated as a stray:\n"
            f"{result.stdout}\n{result.stderr}")
        assert "###" not in open(os.path.join(directory, "version.json")).read()


def test_a_file_that_appears_while_the_stamp_is_written_stops_the_build():
    """
    The guard firing, rather than merely not misfiring.

    Proven by making the substitution itself produce one: with `sed -i` on BSD the backup
    suffix defect is exactly this, and it is what shipped `version.json-e` to the internet.
    """
    with tempfile.TemporaryDirectory() as directory:
        destination = os.path.join(directory, "version.json")
        with open(TEMPLATES["backend"]) as source, open(destination, "w") as copy:
            copy.write(source.read())

        # A `write_version_json` whose substitution leaves something behind, which is what the
        # function did until this was fixed.
        result = subprocess.run(
            ["bash", "-c",
             f'source "{_COMMON}" >/dev/null 2>&1; '
             f'original=$(declare -f write_version_json); '
             f'eval "${{original/sed -e/touch \"{destination}-e\"; sed -e}}"; '
             f'write_version_json "{destination}" "{BRANCH}" "{SHA}" "7"'],
            capture_output=True, text=True)
        assert result.returncode != 0, (
            "a file that appeared beside the version stamp was published without comment")
        assert "version.json-e" in (result.stdout + result.stderr), (
            "the build stopped without naming the file it was about to publish")


def test_a_template_that_cannot_be_filled_in_stops_the_build():
    """
    The check that would have caught the original defect. Shipping a half-substituted stamp
    quietly is what made this survive from September to October unnoticed.
    """
    with tempfile.TemporaryDirectory() as directory:
        destination = os.path.join(directory, "version.json")
        with open(destination, "w") as f:
            f.write('{"date": "###date###", "sha": "###NOT_A_PLACEHOLDER_WE_FILL###"}')
        result = subprocess.run(
            ["bash", "-c",
             f'source "{_COMMON}" >/dev/null 2>&1; '
             f'write_version_json "{destination}" "{BRANCH}" "{SHA}" "7"'],
            capture_output=True, text=True)
        assert result.returncode != 0, (
            "a stamp with an unsubstituted placeholder was accepted and would be published")
        assert "placeholder" in (result.stdout + result.stderr).lower(), (
            "the build stopped without saying what was wrong with the file")


def test_both_build_scripts_use_the_one_implementation():
    """
    There were two copies and both had both defects. One copy is the fix for that.
    """
    for script in ("build-and-upload-fe.sh", "build-and-upload-be.sh"):
        source = open(os.path.join(_SCRIPTS, script)).read()
        assert "function write_version_json" not in source, (
            f"{script} has its own copy again, which is how one fix became two defects")
        assert "write_version_json " in source, f"{script} no longer writes a version stamp"


def test_no_gnu_only_idiom_comes_back():
    """
    Belt and braces for the two specifically, since the deployment runs on a laptop and CI
    would never show the difference.
    """
    for script in ("common.sh", "build-and-upload-fe.sh", "build-and-upload-be.sh"):
        for line in open(os.path.join(_SCRIPTS, script)):
            if line.lstrip().startswith("#"):
                continue
            assert "sed -i" not in line, (
                f"{script} uses `sed -i`, whose backup behaviour differs between BSD and GNU:"
                f"\n  {line.strip()}")
            assert "%N" not in line, (
                f"{script} uses a %N date format, which BSD date does not have:\n  {line.strip()}")


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
