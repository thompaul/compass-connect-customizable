#!/usr/bin/env python3
"""
No Pulumi module directory may shadow an installed package.

`iac/dns` carried an `__init__.py`, which made it an importable package named `dns`. The
scripts put the iac root first on sys.path so that modules can import `lib`, so from that
point on `import dns` meant this repository. dnspython became unreachable for the whole
process, and a `mongodb+srv://` connection string - which needs dnspython to look up its
SRV record - failed as

    ConfigurationError: cannot import name 'resolver' from 'dns' (iac/dns/__init__.py)

naming neither the cause nor the fix. It had been latent for years: nothing in the IaC
resolved DNS until the pre-flight checks did.

The fix was to stop the directory being a package. A directory with no `__init__.py` is at
most a namespace portion, and a real installed package always beats one. That holds for
every module here, so this is the general version of it.

Runnable directly: `python3 test_module_names.py` from the iac directory.
"""
import importlib.util
import os
import sys

_IAC = os.path.dirname(os.path.abspath(__file__))

#: Directories here that are meant to be imported by name, and so are allowed to be
#: packages. `lib` is the shared code every module imports; it is not a Pulumi project.
IMPORTABLE_BY_DESIGN = {"lib"}


def _module_directories() -> list:
    """Every directory the import system would see with the iac root on sys.path."""
    return sorted(name for name in os.listdir(_IAC)
                  if os.path.isdir(os.path.join(_IAC, name))
                  and not name.startswith((".", "_"))
                  and name not in ("venv-iac", "templates", "keys"))


def _installed_elsewhere(name: str) -> str:
    """
    Where the import system would find this name without the iac root, or ''.

    Both the path and sys.modules have to be set aside: find_spec returns a cached
    module's own spec, so an earlier import of the shadowing package would otherwise be
    reported as the thing it shadows.
    """
    without_iac = [p for p in sys.path if os.path.abspath(p or ".") != _IAC]
    cached = {key: module for key, module in list(sys.modules.items())
              if key == name or key.startswith(name + ".")}
    for key in cached:
        del sys.modules[key]
    saved, sys.path[:] = sys.path[:], without_iac
    try:
        spec = importlib.util.find_spec(name)
    except (ImportError, ValueError):
        return ""
    finally:
        sys.path[:] = saved
        for key in list(sys.modules):
            if key == name or key.startswith(name + "."):
                del sys.modules[key]
        sys.modules.update(cached)
    return (getattr(spec, "origin", None) or "") if spec else ""


def test_no_module_directory_shadows_an_installed_package():
    """
    The invariant that was broken.

    A directory is only a package if it has an `__init__.py`; without one it cannot win
    against an installed distribution of the same name. Anything a module needs to share
    belongs in `lib`, which is imported deliberately.
    """
    clashes = []
    for name in _module_directories():
        if name in IMPORTABLE_BY_DESIGN:
            continue
        if not os.path.exists(os.path.join(_IAC, name, "__init__.py")):
            continue
        elsewhere = _installed_elsewhere(name)
        if elsewhere:
            clashes.append(f"    iac/{name}/__init__.py shadows {elsewhere}")
    assert not clashes, (
        "these module directories are importable packages whose names are already taken:\n"
        + "\n".join(clashes)
        + "\nRemove the __init__.py - a directory without one cannot shadow an installed "
          "package. Anything it declared moves to its consumer, or to lib.")


def test_dnspython_is_reachable_with_the_iac_root_on_the_path():
    """The instance, kept because it is the one that cost real time."""
    cached = {key: module for key, module in list(sys.modules.items())
              if key == "dns" or key.startswith("dns.")}
    for key in cached:
        del sys.modules[key]
    sys.path.insert(0, _IAC)
    try:
        import dns  # noqa: PLC0415
        where = dns.__file__ or ""
    except ImportError:
        return  # dnspython is optional; if it is absent there is nothing to shadow
    finally:
        sys.path.remove(_IAC)
        for key in list(sys.modules):
            if key == "dns" or key.startswith("dns."):
                del sys.modules[key]
        sys.modules.update(cached)
    assert not os.path.abspath(where).startswith(_IAC + os.sep), (
        f"`import dns` resolves to {where}, not dnspython. A mongodb+srv:// connection "
        f"string cannot resolve its SRV record while this is true.")


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
            print(f"FAIL {_name}:\n{_e}")
    print(f"\n{'FAILED' if _failed else 'OK'} - {_failed} failed")
    sys.exit(1 if _failed else 0)
