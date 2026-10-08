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

import json
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



class _Resp:
    def __init__(self, status):
        self.status = status
        self.reason = "Bad Request"


def _http_error(detail):
    from googleapiclient.errors import HttpError
    return HttpError(_Resp(400), f'{{"error": {{"message": "{detail}"}}}}'.encode())


class CallbackUriTest(unittest.TestCase):
    """
    The email action handler is the one field Identity Platform will not take on a custom
    domain. It answers EMAIL_TEMPLATE_UPDATE_NOT_ALLOWED for anything that is not the
    project's own firebaseapp.com or web.app address, so sending it with the rest of the
    email configuration loses all of it over the one field that could never be set.
    """

    IN_USE = {"notification": {"sendEmail": {"callbackUri": "https://p.firebaseapp.com/__/auth/action"}}}

    def test_a_rejected_handler_does_not_fail_the_deployment(self):
        def _raise(*_a, **_kw):
            raise _http_error("EMAIL_TEMPLATE_UPDATE_NOT_ALLOWED")

        with mock.patch.object(identity_platform, "_identity_platform_update_config", _raise), \
             mock.patch.object(identity_platform.pulumi, "warn") as warned:
            result = identity_platform._apply_callback_uri(
                None, "p", "https://custom.example.com/#/auth-handler", self.IN_USE)

        self.assertEqual(result, self.IN_USE, "the configuration in force is returned unchanged")
        warned.assert_called_once()

    def test_the_warning_says_what_users_will_see(self):
        def _raise(*_a, **_kw):
            raise _http_error("EMAIL_TEMPLATE_UPDATE_NOT_ALLOWED")

        with mock.patch.object(identity_platform, "_identity_platform_update_config", _raise), \
             mock.patch.object(identity_platform.pulumi, "warn") as warned:
            identity_platform._apply_callback_uri(
                None, "p", "https://custom.example.com/#/auth-handler", self.IN_USE)

        message = warned.call_args[0][0]
        self.assertIn("https://p.firebaseapp.com/__/auth/action", message,
                      "the address actually in force must be named")
        self.assertIn("https://custom.example.com/#/auth-handler", message,
                      "the address that was refused must be named")
        self.assertIn("reset", message, "the user-visible consequence must be stated")

    def test_any_other_failure_still_fails(self):
        """Only this one refusal is tolerated; a real error is not swallowed."""
        def _raise(*_a, **_kw):
            raise _http_error("PERMISSION_DENIED")

        with mock.patch.object(identity_platform, "_identity_platform_update_config", _raise):
            with self.assertRaises(Exception):
                identity_platform._apply_callback_uri(
                    None, "p", "https://custom.example.com/", self.IN_USE)

    def test_a_handler_that_is_accepted_is_used(self):
        applied = {}

        def _ok(_c, _p, cfg, **_kw):
            applied.update(cfg)
            return {"notification": {"sendEmail": {"callbackUri": "https://p.web.app/x"}}}

        with mock.patch.object(identity_platform, "_identity_platform_update_config", _ok), \
             mock.patch.object(identity_platform.pulumi, "warn") as warned:
            result = identity_platform._apply_callback_uri(
                None, "p", "https://p.web.app/x", self.IN_USE)

        self.assertEqual(applied["notification"]["sendEmail"]["callbackUri"], "https://p.web.app/x")
        self.assertNotEqual(result, self.IN_USE, "the newly applied config is returned")
        warned.assert_not_called()




class ApplyConfigPhasesTest(unittest.TestCase):
    """
    The three-way split of the apply. Nothing that depends on a verified domain may be sent
    before the domain is verified, and the action handler must not ride along with the rest:
    the API rejects the whole request over that one field, so sending them together loses
    the email configuration entirely.
    """

    BODY = {
        "signIn": {"email": {"enabled": True}},
        "authorizedDomains": ["prod.example.com"],
        "notification": {
            "sendEmail": {
                "callbackUri": "https://prod.example.com/#/auth-handler",
                "dnsInfo": {"useCustomDomain": True},
                "verifyEmailTemplate": {"senderLocalPart": "noreply"},
            }
        },
    }

    def _apply(self):
        sent = []
        order = []

        def _update(_c, _p, cfg, **_kw):
            sent.append(cfg)
            order.append("update")
            return {"notification": {"sendEmail": {"callbackUri": "https://p.firebaseapp.com/x"}}}

        with mock.patch.object(identity_platform, "get_credentials", lambda: object()), \
             mock.patch.object(identity_platform, "_identity_platform_get_config", lambda *_a: {"x": 1}), \
             mock.patch.object(identity_platform, "_getconfig_for_api_body",
                               lambda _props: json.loads(json.dumps(self.BODY))), \
             mock.patch.object(identity_platform, "_verify_domain",
                               lambda *_a: order.append("verify")), \
             mock.patch.object(identity_platform, "_identity_platform_update_config", _update), \
             mock.patch.object(identity_platform, "convert_keys_to_snake_case", lambda c: c), \
             mock.patch.object(identity_platform.pulumi, "warn"):
            identity_platform._apply_config({"project": "p", "resource_name": "r"})
        return sent, order

    def test_the_first_request_carries_nothing_that_needs_a_verified_domain(self):
        sent, order = self._apply()
        self.assertNotIn("notification", sent[0],
                         "the email configuration must wait for the domain")
        self.assertEqual(order[0], "update")
        self.assertEqual(order[1], "verify", "verification comes after the first request")

    def test_the_action_handler_is_not_sent_with_the_rest(self):
        sent, _order = self._apply()
        email = sent[1].get("notification", {}).get("sendEmail", {})
        self.assertNotIn("callbackUri", email,
                         "a refused handler would take the whole email configuration with it")
        self.assertIn("dnsInfo", email, "the rest of the email configuration is still sent")

    def test_the_action_handler_is_attempted_on_its_own(self):
        sent, _order = self._apply()
        self.assertEqual(len(sent), 3, "three requests: the rest, the email config, the handler")
        self.assertEqual(sent[2]["notification"]["sendEmail"]["callbackUri"],
                         "https://prod.example.com/#/auth-handler")
        self.assertEqual(list(sent[2]["notification"]["sendEmail"].keys()), ["callbackUri"],
                         "the handler is sent alone so only it can be refused")



if __name__ == "__main__":
    unittest.main(verbosity=2)
