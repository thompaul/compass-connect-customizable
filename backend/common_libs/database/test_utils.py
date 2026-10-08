"""
A database that will not answer must say why, and must not say the password.

Four failures used to be indistinguishable - a wrong password, an unresolvable host, a
TLS error and an IP the cluster's access list does not admit all produced the single
sentence "MongoDB health check failed for <X> database". Every one of them is named by
the driver; a boolean return was what threw the name away. These tests pin both halves:
the cause survives, and the credential does not.
"""
import asyncio
import logging
import unittest

from common_libs.database.utils import (
    mongo_health_error,
    open_mongo_client,
    redact_mongodb_uri,
    require_healthy_database,
    scrub_mongodb_credentials,
)

URI = "mongodb+srv://compass_user:sup3r-s3cret@cluster0.abcde.mongodb.net/?retryWrites=true"
PASSWORD = "sup3r-s3cret"


class _Admin:
    def __init__(self, outcome):
        self._outcome = outcome

    async def command(self, _name):
        if isinstance(self._outcome, Exception):
            raise self._outcome
        return self._outcome


class _Client:
    """Enough of a motor client for the health check: an admin database and an address."""

    def __init__(self, outcome):
        self.admin = _Admin(outcome)
        self.nodes = set()
        self.address = None

    async def server_info(self):
        raise RuntimeError("no server")


class _Database:
    def __init__(self, outcome, name="compass_application"):
        self.client = _Client(outcome)
        self.name = name


def run(coroutine):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coroutine)


class RedactionTest(unittest.TestCase):
    def test_the_password_is_replaced(self):
        redacted = redact_mongodb_uri(URI)
        self.assertNotIn(PASSWORD, redacted)
        self.assertIn("compass_user:***@cluster0.abcde.mongodb.net", redacted)

    def test_the_user_and_host_survive(self):
        """Redacting to nothing would be safe and useless: the operator needs to see which
        cluster and which user, to tell one of six connection strings from another."""
        self.assertIn("compass_user", redact_mongodb_uri(URI))
        self.assertIn("cluster0.abcde.mongodb.net", redact_mongodb_uri(URI))

    def test_a_uri_with_no_credentials_is_unharmed(self):
        self.assertEqual("mongodb://localhost:27017/compass",
                         redact_mongodb_uri("mongodb://localhost:27017/compass"))

    def test_rubbish_does_not_raise(self):
        self.assertEqual("<no connection string>", redact_mongodb_uri(""))
        self.assertEqual("<connection string>", redact_mongodb_uri("not-a-uri"))

    def test_a_password_quoted_back_by_the_driver_is_scrubbed(self):
        """The driver repeats the whole connection string in several of its errors."""
        message = f"ConfigurationError: could not resolve {URI}"
        self.assertNotIn(PASSWORD, scrub_mongodb_credentials(message, URI))

    def test_a_password_is_scrubbed_even_without_the_uri_to_compare(self):
        """A pooled client reports a rewritten URI that never matches the one configured."""
        message = "ServerSelectionTimeoutError: mongodb://compass_user:sup3r-s3cret@node-1:27017"
        scrubbed = scrub_mongodb_credentials(message)
        self.assertNotIn(PASSWORD, scrubbed)
        self.assertIn("compass_user:***@node-1:27017", scrubbed)


class OpenClientTest(unittest.TestCase):
    """A connection string the driver will not take fails before there is a ping to fail."""

    def test_an_unresolvable_srv_host_is_named(self):
        """The driver resolves the SRV record while parsing, so this raises in the
        constructor and never reaches the health check at all. It used to come out as a
        bare ConfigurationError traceback with no indication of which database."""
        with self.assertRaises(RuntimeError) as raised:
            open_mongo_client("mongodb+srv://compass_user:%s@no-such-cluster.abcde.mongodb.net/"
                              % PASSWORD)
        message = str(raised.exception)
        self.assertIn("no-such-cluster.abcde.mongodb.net", message)
        self.assertIn("ConfigurationError", message)
        self.assertNotIn(PASSWORD, message)

    def test_a_malformed_connection_string_does_not_quote_itself_back(self):
        with self.assertRaises(RuntimeError) as raised:
            open_mongo_client("mongodb://compass_user:%s@:::/" % PASSWORD)
        self.assertNotIn(PASSWORD, str(raised.exception))


class HealthErrorTest(unittest.TestCase):
    def test_a_healthy_ping_reports_nothing(self):
        self.assertIsNone(run(mongo_health_error(_Client({"ok": 1.0}))))

    def test_the_drivers_exception_class_is_kept(self):
        class OperationFailure(Exception):
            pass

        failure = run(mongo_health_error(_Client(OperationFailure("bad auth : authentication failed"))))
        self.assertIn("OperationFailure", failure)
        self.assertIn("bad auth", failure)

    def test_a_refusal_that_is_not_an_exception_is_still_a_failure(self):
        """`ok: 0` is a refusal, and `ok` missing entirely used to raise inside the check
        itself and be swallowed as an unrelated False."""
        self.assertIsNotNone(run(mongo_health_error(_Client({"ok": 0.0}))))
        self.assertIsNotNone(run(mongo_health_error(_Client({}))))


class RequireHealthyDatabaseTest(unittest.TestCase):
    def setUp(self):
        self.logger = logging.getLogger("test-require-healthy")
        self.logger.propagate = False

    def _failure(self, exception, database="compass_application"):
        with self.assertLogs(self.logger, level="WARNING") as logged:
            with self.assertRaises(RuntimeError) as raised:
                run(require_healthy_database(_Database(exception, database),
                                             label="Application", mongodb_uri=URI,
                                             logger=self.logger))
        return str(raised.exception), "\n".join(logged.output)

    def test_a_bad_password_names_the_drivers_error(self):
        class OperationFailure(Exception):
            pass

        raised, logged = self._failure(OperationFailure("bad auth : authentication failed"))
        for text in (raised, logged):
            self.assertIn("OperationFailure", text)
            self.assertIn("bad auth : authentication failed", text)

    def test_the_failure_names_which_database(self):
        """Six connection strings, so "a database failed" is not an answer."""
        raised, _ = self._failure(Exception("boom"), database="compass_taxonomy")
        self.assertIn("Application", raised)
        self.assertIn("compass_taxonomy", raised)

    def test_an_unreachable_host_is_distinguishable_from_a_bad_password(self):
        class ServerSelectionTimeoutError(Exception):
            pass

        timeout, _ = self._failure(ServerSelectionTimeoutError("No replica set members"))
        self.assertIn("ServerSelectionTimeoutError", timeout)

    def test_no_credential_reaches_the_log_or_the_exception(self):
        raised, logged = self._failure(Exception(f"failed to connect to {URI}"))
        self.assertNotIn(PASSWORD, raised)
        self.assertNotIn(PASSWORD, logged)
        self.assertIn("cluster0.abcde.mongodb.net", raised)

    def test_a_healthy_database_is_silent(self):
        run(require_healthy_database(_Database({"ok": 1.0}), label="Application",
                                     mongodb_uri=URI, logger=self.logger))


if __name__ == "__main__":
    unittest.main(verbosity=2)
