#!/usr/bin/env python3
"""
The checks that need the outside world, driven against a stand-in for the database.

Two things matter beyond "does it find the fault". A pre-flight report is pasted into
bug reports and CI logs, so **no message may carry a credential** — including the
driver's own exception text, which repeats the whole connection string. And several of
these variables normally name one cluster, so it must not open six connections to prove
one password is wrong.
"""

import os
import sys

_SCRIPTS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(_SCRIPTS, '..')))
sys.path.insert(0, _SCRIPTS)

import _preflight
from _preflight import redact, check_databases, check_taxonomy_model, run_live_checks

SECRET = "hunter2correcthorse"
URI = f"mongodb+srv://compass:{SECRET}@cluster0.abcde.mongodb.net/?retryWrites=true"

ENV = {
    "TAXONOMY_MONGODB_URI": URI, "TAXONOMY_DATABASE_NAME": "tax",
    "APPLICATION_MONGODB_URI": URI, "APPLICATION_DATABASE_NAME": "app",
    "USERDATA_MONGODB_URI": URI, "USERDATA_DATABASE_NAME": "user",
    "TAXONOMY_MODEL_ID": "6a5b9bfd9f21e9bf96634956",
    "EMBEDDINGS_SERVICE_NAME": "GOOGLE-VERTEX-AI",
    "EMBEDDINGS_MODEL_NAME": "text-embedding-005",
}


class FakeObjectId(str):
    pass


def driver(client):
    """A stand-in for the pymongo import, as _load_driver returns it."""
    return lambda: (client, FakeObjectId, ValueError)


class Client:
    """Records how it was used, and fails however the test asks it to."""
    opened = []

    def __init__(self, uri, serverSelectionTimeoutMS=None, fail=None, doc=None):
        Client.opened.append(uri)
        self._fail = fail
        self._doc = doc
        self.admin = self
        self.closed = False

    def __call__(self, uri, serverSelectionTimeoutMS=None):
        return type(self)(uri, serverSelectionTimeoutMS,
                          fail=self._fail, doc=self._doc)

    def command(self, _name):
        if self._fail:
            raise RuntimeError(self._fail)

    def __getitem__(self, _name):
        return self

    def list_collection_names(self):
        if self._fail:
            raise RuntimeError(self._fail)
        return []

    def find_one(self, _query):
        return self._doc

    def close(self):
        self.closed = True


def _with(client, fn):
    original = _preflight._load_driver
    _preflight._load_driver = driver(client)
    Client.opened = []
    try:
        return fn()
    finally:
        _preflight._load_driver = original


def test_a_password_never_appears_in_a_report():
    """The driver repeats the whole URI in its errors; the report must not."""
    client = Client(URI, fail=f"authentication failed for {URI}")
    problems = _with(client, lambda: check_databases(ENV))
    assert problems, "a failing connection should be reported"
    for problem in problems:
        assert SECRET not in problem, f"password leaked: {problem}"
        assert "***" in problem, f"expected a redacted form, got: {problem}"


def test_redact_keeps_what_identifies_the_cluster():
    out = redact(URI)
    assert SECRET not in out
    assert "cluster0.abcde.mongodb.net" in out and "compass" in out


def test_redact_survives_rubbish():
    assert redact("not a uri at all") in ("<connection string>", "<unparseable connection string>")
    assert redact("") in ("<connection string>", "<unparseable connection string>")


def test_one_cluster_is_opened_once_per_check_not_once_per_variable():
    client = Client(URI)
    _with(client, lambda: check_databases(ENV))
    distinct = set(Client.opened)
    assert len(distinct) == 1, f"expected one cluster, got {distinct}"


def test_a_reachable_configuration_reports_nothing():
    client = Client(URI)
    assert _with(client, lambda: check_databases(ENV)) == []


def test_a_missing_driver_is_a_sentence_not_a_crash():
    original = _preflight._load_driver
    _preflight._load_driver = lambda: None
    try:
        problems = check_databases(ENV)
    finally:
        _preflight._load_driver = original
    assert len(problems) == 1 and "driver is not installed" in problems[0], problems


def test_an_absent_database_is_left_to_the_template_check():
    client = Client(URI)
    problems = _with(client, lambda: check_databases({"TAXONOMY_MONGODB_URI": "", "TAXONOMY_DATABASE_NAME": ""}))
    assert problems == [], problems


def test_a_model_that_is_not_there_says_so():
    client = Client(URI, doc=None)
    problems = _with(client, lambda: check_taxonomy_model(ENV))
    assert len(problems) == 1 and "is not in modelinfos" in problems[0], problems


def test_an_unusable_model_id_is_named_before_any_lookup():
    client = Client(URI, doc=None)

    class Strict(FakeObjectId):
        def __new__(cls, value):
            raise ValueError("not an ObjectId")

    original = _preflight._load_driver
    _preflight._load_driver = lambda: (client, Strict, ValueError)
    try:
        problems = check_taxonomy_model({**ENV, "TAXONOMY_MODEL_ID": "nonsense"})
    finally:
        _preflight._load_driver = original
    assert len(problems) == 1 and "not a valid identifier" in problems[0], problems


def test_embeddings_generated_by_another_model_are_refused():
    """The worst case: the deployment starts, and skills search silently compares nonsense."""
    doc = {"modelId": "x", "embeddingsService": {
        "service_name": "GOOGLE-VERTEX-AI", "model_name": "textembedding-gecko"}}
    client = Client(URI, doc=doc)
    problems = _with(client, lambda: check_taxonomy_model(ENV))
    assert len(problems) == 1, problems
    assert "textembedding-gecko" in problems[0] and "text-embedding-005" in problems[0], problems


def test_matching_embeddings_pass():
    doc = {"modelId": "x", "embeddingsService": {
        "service_name": "GOOGLE-VERTEX-AI", "model_name": "text-embedding-005"}}
    client = Client(URI, doc=doc)
    assert _with(client, lambda: check_taxonomy_model(ENV)) == []


def test_a_model_with_no_recorded_embeddings_is_allowed_through():
    """The application warns and continues here, so the pre-flight must not be stricter."""
    client = Client(URI, doc={"modelId": "x"})
    assert _with(client, lambda: check_taxonomy_model(ENV)) == []



def test_an_unreachable_cluster_is_not_asked_a_second_question():
    """
    One failure, reported once. Asking the model question anyway produces a second
    message about the same broken connection, under a name that suggests another fault.
    """
    client = Client(URI, fail="bad auth : authentication failed")
    problems = _with(client, lambda: run_live_checks(ENV))
    assert len(problems) == 1, problems
    assert "could not be reached" in problems[0], problems
    assert all("taxonomy model could not be looked up" not in p for p in problems), problems


def test_a_cluster_named_by_six_variables_is_reported_once_and_names_them():
    client = Client(URI, fail="bad auth : authentication failed")
    problems = _with(client, lambda: check_databases(ENV))
    assert len(problems) == 1, problems
    for key in ("TAXONOMY_MONGODB_URI", "APPLICATION_MONGODB_URI", "USERDATA_MONGODB_URI"):
        assert key in problems[0], problems


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
