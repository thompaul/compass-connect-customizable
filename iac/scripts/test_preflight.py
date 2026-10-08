#!/usr/bin/env python3
"""
Configuration validation reports everything wrong with a configuration, once.

It used to stop at the first fault, in each of two checks run one after the other. An
operator supplying a configuration for the first time therefore learned about one missing
value per attempt - and an attempt means uploading a secret, running prepare, and reading
a cloud error. The list is the whole point.
"""

import os
import sys

# Both directories are needed: this module's own imports resolve from scripts/, and
# _types reaches into environment/ from the iac root.
_SCRIPTS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(_SCRIPTS, '..')))
sys.path.insert(0, _SCRIPTS)

from _common import collect_template_problems, find_placeholder_values, report_problems

TEMPLATE = {
    "REQUIRED_A": "",
    "REQUIRED_B": "",
    "OPTIONAL": "/.*/",
    "CONSTRAINED": "/(true|false)/",
}


def test_every_fault_is_reported_not_just_the_first():
    problems = collect_template_problems(
        template=TEMPLATE,
        actual_cfg={"REQUIRED_A": "", "REQUIRED_B": "", "CONSTRAINED": "maybe"})
    assert len(problems) == 3, f"expected all three, got {problems}"
    joined = " ".join(problems)
    for key in ("REQUIRED_A", "REQUIRED_B", "CONSTRAINED"):
        assert key in joined, f"{key} missing from {problems}"


def test_a_missing_required_value_reads_differently_from_a_wrong_one():
    """"Required but empty" and "does not match" are different mistakes to fix."""
    empty = collect_template_problems(
        template={"K": ""}, actual_cfg={"K": ""})
    wrong = collect_template_problems(
        template={"K": "/(true|false)/"}, actual_cfg={"K": "perhaps"})
    assert "required but has no value" in empty[0], empty
    assert "does not match" in wrong[0], wrong


def test_an_optional_value_may_be_absent():
    assert collect_template_problems(
        template=TEMPLATE,
        actual_cfg={"REQUIRED_A": "a", "REQUIRED_B": "b", "CONSTRAINED": "true"}) == []


def test_nested_groups_recurse_and_still_report_everything():
    problems = collect_template_problems(
        template={"group": {"X": "", "Y": ""}, "top": ""},
        actual_cfg={"group": {"X": "", "Y": ""}, "top": ""})
    assert len(problems) == 3, problems
    assert any("group.X" in p for p in problems), problems
    assert any("group.Y" in p for p in problems), problems


def test_a_group_supplied_as_a_scalar_is_reported_without_crashing():
    problems = collect_template_problems(
        template={"group": {"X": ""}}, actual_cfg={"group": "oops"})
    assert len(problems) == 1 and "group" in problems[0], problems


def test_extra_keys_do_not_fail_unless_strict():
    extra = {"REQUIRED_A": "a", "REQUIRED_B": "b", "CONSTRAINED": "true", "MINE": "x"}
    assert collect_template_problems(template=TEMPLATE, actual_cfg=extra) == []
    strict = collect_template_problems(template=TEMPLATE, actual_cfg=extra, strict=True)
    assert len(strict) == 1 and "MINE" in strict[0], strict


def test_placeholders_are_named():
    """A value nobody filled in should say so, not fail later as a bad hostname."""
    problems = find_placeholder_values({
        "URI": "<MONGODB_URI>",
        "OTHER": "__ATLAS_URI__",
        "FINE": "mongodb+srv://real.example.com",
        "ALSO_FINE": "",
    })
    assert len(problems) == 2, problems
    assert any("URI" in p and "<MONGODB_URI>" in p for p in problems), problems
    assert all("FINE" not in p for p in problems), problems


def test_the_templates_own_markers_are_caught_whatever_their_shape():
    """Half the template's markers are not capitals - <True/False> is one."""
    problems = find_placeholder_values({"A": "<True/False>", "B": "<model-id>", "C": "<URI>"})
    assert len(problems) == 3, problems


def test_a_real_value_that_merely_looks_shouty_is_not_a_placeholder():
    assert find_placeholder_values({
        "A": "PRODUCTION",
        "B": "a<b>c",
        "C": "<not a placeholder>",
        "D": "mongodb+srv://u:p@host/db?retryWrites=true",
        "E": '{"primary": "#123456"}',
    }) == []


def test_report_says_clean_only_when_it_is():
    assert report_problems([], subject="x") is True
    assert report_problems(["something"], subject="x") is False


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
            print(f"FAIL {_name}: {_e}")
    print(f"\n{'FAILED' if _failed else 'OK'} - {_failed} failed")
    sys.exit(1 if _failed else 0)
