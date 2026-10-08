#!/usr/bin/env python3
"""
Tests for the custom-domain verification loop of the Identity Platform.

The loop exists because verification is not instant. It was unreachable: the service
returns a transient reason alongside an IN_PROGRESS state while it waits for a newly
created project's Firebase namespace to appear, and any reason at all was treated as
terminal. The first poll therefore always ended the deployment, and the only reason this
was not noticed is that a deployment done by hand takes long enough between creating the
project and reaching this code that the reason has gone by the time it runs.
"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import identity_platform

PROPS = {
    "notification": {
        "send_email": {
            "dns_info": {
                "use_custom_domain": True,
                "custom_domain": "prod.example.com",
            }
        }
    }
}

NAMESPACE_PENDING = "Firebase namespace check failed: couldn't find expected namespace: p"


class _Clock:
    """A clock that only moves when the code under test waits, so tests are instant."""

    def __init__(self):
        self.now = 0.0
        self.slept = []

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += seconds


def drive(responses, *, timeout=None, repeat_last=True):
    """
    Drive _verify_domain over a scripted sequence of VERIFY replies.

    Returns the actions it asked for and the clock it ran against.
    """
    calls = []
    replies = list(responses)
    clock = _Clock()

    def _fake(_credentials, _project, _domain, action):
        calls.append(action)
        if action != "VERIFY":
            return "SUCCEEDED", ""
        if len(replies) > 1 or not repeat_last:
            return replies.pop(0)
        return replies[0]

    env = {} if timeout is None else {"COMPASS_DOMAIN_VERIFICATION_TIMEOUT_SECS": str(timeout)}
    with mock.patch.object(identity_platform, "_identity_platform_verify_domain", _fake), \
         mock.patch.object(identity_platform, "time", clock), \
         mock.patch.dict(os.environ, env, clear=(timeout is None)):
        identity_platform._verify_domain(None, "p", PROPS)
    return calls, clock


class VerifyDomainTest(unittest.TestCase):

    def test_waits_through_a_transient_reason_and_succeeds(self):
        """An IN_PROGRESS carrying a reason is waited out, not treated as a failure."""
        calls, _clock = drive([
            ("IN_PROGRESS", NAMESPACE_PENDING),
            ("IN_PROGRESS", NAMESPACE_PENDING),
            ("SUCCEEDED", ""),
        ], repeat_last=False)
        self.assertEqual(calls.count("VERIFY"), 3, "should have polled until it succeeded")
        self.assertIn("APPLY", calls, "a successful verification must be applied")
        self.assertNotIn("CANCEL", calls, "nothing failed, so nothing should be cancelled")

    def test_a_failed_state_is_still_terminal(self):
        """A genuine FAILED is not waited out - it cancels and raises."""
        with self.assertRaises(identity_platform.DomainVerificationError):
            drive([("FAILED", "the domain is owned by someone else")])

    def test_running_out_of_time_says_it_can_be_resumed(self):
        """Exhausting the bound explains the cause and that re-running continues."""
        with self.assertRaises(TimeoutError) as caught:
            drive([("IN_PROGRESS", NAMESPACE_PENDING)], timeout=120)
        message = str(caught.exception)
        self.assertIn(NAMESPACE_PENDING, message, "the reason it was waiting must be reported")
        self.assertIn("re-run", message, "the operator must be told this is resumable")

    def test_the_default_bound_outlasts_the_five_minutes_that_never_sufficed(self):
        """Left unset, the wait is long enough to be worth making."""
        with self.assertRaises(TimeoutError):
            _calls, clock = drive([("IN_PROGRESS", NAMESPACE_PENDING)])
        # The loop raises, so read the elapsed time off a run we can inspect instead.
        elapsed = self._elapsed_before_timeout()
        self.assertGreater(elapsed, 300, "five minutes was never enough for a new project")

    def _elapsed_before_timeout(self):
        clock = _Clock()
        calls = []

        def _fake(_c, _p, _d, action):
            calls.append(action)
            return ("IN_PROGRESS", NAMESPACE_PENDING) if action == "VERIFY" else ("SUCCEEDED", "")

        with mock.patch.object(identity_platform, "_identity_platform_verify_domain", _fake), \
             mock.patch.object(identity_platform, "time", clock), \
             mock.patch.dict(os.environ, {}, clear=True):
            try:
                identity_platform._verify_domain(None, "p", PROPS)
            except TimeoutError:
                pass
        return clock.now

    def test_polling_interval_is_not_wasteful(self):
        """Half an hour of one-second polls would be churn; the interval is coarse."""
        _calls, clock = drive([
            ("IN_PROGRESS", NAMESPACE_PENDING),
            ("SUCCEEDED", ""),
        ], repeat_last=False)
        self.assertGreaterEqual(clock.slept[0], 30)


if __name__ == "__main__":
    unittest.main(verbosity=2)
