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
import os
import unittest

from pymongo.errors import AutoReconnect, ConfigurationError, OperationFailure, \
    ServerSelectionTimeoutError

from common_libs.database import utils
from common_libs.database.utils import (
    DEFAULT_STARTUP_BUDGET_SECONDS,
    STARTUP_BUDGET_VARIABLE,
    database_startup_budget_seconds,
    is_transient_database_failure,
    mongo_health_error,
    open_mongo_client,
    redact_mongodb_uri,
    require_healthy_database,
    scrub_mongodb_credentials,
)

# An invented credential, and the point of the tests below: every one of them asserts that this
# string does not reach a log line or an exception message. It has to be a literal for that to
# mean anything - a password assembled at runtime would not prove the redaction works on the
# shape a real connection string has.
URI = "mongodb+srv://compass_user:sup3r-s3cret@cluster0.abcde.mongodb.net/?retryWrites=true"  # nosec B105 # invented credential, asserted never to be logged
PASSWORD = "sup3r-s3cret"  # nosec B105 # invented credential, asserted never to be logged


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
    loop = asyncio.get_event_loop_policy().new_event_loop()
    try:
        return loop.run_until_complete(coroutine)
    finally:
        # Closed here rather than left to the garbage collector, which runs it at interpreter
        # shutdown when the selector is already gone and prints a traceback that looks like a
        # test failure and is not.
        loop.close()


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



# --- Who is allowed to give up, and when -----------------------------------------------
#
# The backend used to exit when a database did not answer within PyMongo's default 30
# seconds. Cloud Run then destroyed the instance, waited, and started another - which
# succeeded, every time, with the same image and the same credentials. The user paid just
# under two minutes for a retry the process could have done itself in a quarter of a second.
#
# Neither of the two numbers that produced that was chosen by anyone: not the driver's 30
# seconds, and not the platform's one-strike startup probe. These tests pin the decisions
# that replaced them, and the one thing that must not change with them - that a deployment
# which is simply wrong still stops at once and still says so.


class _CountingDatabase(_Database):
    """Fails with `outcome` for the first `failures` pings, then answers."""

    def __init__(self, outcome, failures, name="compass_application"):
        super().__init__(outcome, name)
        self._remaining = failures
        self.pings = 0
        database = self

        async def command(_name):
            database.pings += 1
            if database._remaining > 0:
                database._remaining -= 1
                raise outcome
            return {"ok": 1.0}

        self.client.admin.command = command


class TransienceTest(unittest.TestCase):
    """Which failures asking again could change the answer to."""

    def test_a_connection_that_could_not_be_made_is_worth_retrying(self):
        for failure in (ServerSelectionTimeoutError("no replica set members available"),
                        AutoReconnect("connection pool paused")):
            self.assertTrue(is_transient_database_failure(failure),
                            f"{type(failure).__name__} would stop the deployment, but the three "
                            f"failures this was written for all cleared within a minute")

    def test_a_deployment_that_is_wrong_is_not(self):
        """Waiting does not discover a different password."""
        for failure in (OperationFailure("bad auth : authentication failed"),
                        ConfigurationError("cannot resolve the SRV record"),
                        utils.DatabaseRefusedPing("the server answered the ping with {'ok': 0.0}")):
            self.assertFalse(is_transient_database_failure(failure),
                             f"{type(failure).__name__} would be retried for the whole startup "
                             f"budget before reporting what it already knew")


class StartupBudgetTest(unittest.TestCase):
    """The number the deployment sets, and what happens when it sets nonsense."""

    def tearDown(self):
        os.environ.pop(STARTUP_BUDGET_VARIABLE, None)

    def test_the_deployment_decides(self):
        os.environ[STARTUP_BUDGET_VARIABLE] = "150"
        self.assertEqual(150.0, database_startup_budget_seconds())

    def test_running_outside_a_deployment_still_has_a_budget(self):
        self.assertEqual(DEFAULT_STARTUP_BUDGET_SECONDS, database_startup_budget_seconds())

    def test_an_unusable_value_is_said_out_loud_rather_than_silently_meaning_zero(self):
        """`float("")` and `float("none")` both raise; `int(...)` of a float string does too.
        Any of them silently becoming "do not retry" would restore the old behaviour in a
        deployment that believed it had configured one."""
        for nonsense in ("", "none", "-1", "two minutes"):
            os.environ[STARTUP_BUDGET_VARIABLE] = nonsense
            with self.assertLogs("common_libs.database.utils", level="WARNING"):
                self.assertEqual(DEFAULT_STARTUP_BUDGET_SECONDS, database_startup_budget_seconds(),
                                 f"{nonsense!r} did not fall back to a usable budget")


class RetryingStartupTest(unittest.TestCase):
    def setUp(self):
        self.logger = logging.getLogger("test-retrying-startup")
        self.logger.propagate = False
        self._pause = utils.SECONDS_BETWEEN_ATTEMPTS
        utils.SECONDS_BETWEEN_ATTEMPTS = 0.01

    def tearDown(self):
        utils.SECONDS_BETWEEN_ATTEMPTS = self._pause

    def test_a_database_that_answers_on_a_later_attempt_starts_the_application(self):
        """
        The measured case. Three cold starts failed and the retry moments later succeeded;
        the retry was done by destroying the instance and starting a new one.
        """
        database = _CountingDatabase(ServerSelectionTimeoutError("no primary"), failures=3)
        run(require_healthy_database(database, label="Application", mongodb_uri=URI,
                                     logger=self.logger, budget_seconds=10))
        self.assertEqual(4, database.pings, "the connection was not retried within the process")

    def test_a_budget_that_runs_out_still_names_the_database_and_the_reason(self):
        database = _CountingDatabase(ServerSelectionTimeoutError("no primary"), failures=99)
        with self.assertRaises(RuntimeError) as raised:
            run(require_healthy_database(database, label="Application", mongodb_uri=URI,
                                         logger=self.logger, budget_seconds=0.05))
        message = str(raised.exception)
        self.assertIn("compass_application", message)
        self.assertIn("ServerSelectionTimeoutError", message)
        self.assertIn("attempts", message, "the operator cannot tell one attempt from twenty")
        self.assertNotIn(PASSWORD, message)

    def test_a_wrong_password_is_not_retried_for_the_whole_budget(self):
        """
        The half of the old design that was right, and has to survive the half that was not.
        A budget of a hundred seconds must not become a hundred seconds of rediscovering
        that the password is wrong.
        """
        database = _CountingDatabase(OperationFailure("bad auth : authentication failed"),
                                     failures=99)
        with self.assertRaises(RuntimeError) as raised:
            run(require_healthy_database(database, label="Application", mongodb_uri=URI,
                                         logger=self.logger, budget_seconds=100))
        self.assertEqual(1, database.pings, "a wrong password was asked about more than once")
        self.assertIn("bad auth", str(raised.exception))

    def test_without_a_budget_nothing_is_retried(self):
        """What a caller wants once the application is serving: a request must not sit
        behind a minute of retries."""
        database = _CountingDatabase(ServerSelectionTimeoutError("no primary"), failures=99)
        with self.assertRaises(RuntimeError):
            run(require_healthy_database(database, label="Application", mongodb_uri=URI,
                                         logger=self.logger))
        self.assertEqual(1, database.pings)


class ClientTimeoutTest(unittest.TestCase):
    """
    The timeouts are set here, not inherited.

    A working ping is answered in about 250ms and a failing one runs to the end of its
    budget, so a long timeout buys a longer wait for the same answer. What the budget should
    be spent on is attempts.
    """

    def test_reaching_a_server_is_given_seconds_not_half_a_minute(self):
        client = open_mongo_client("mongodb://compass_user:%s@node-1:27017/" % PASSWORD)
        selection = client.options.server_selection_timeout
        self.assertEqual(utils.SERVER_SELECTION_TIMEOUT_MS / 1000, selection,
                         "the client is not built from the constant, so the constant no longer "
                         "describes what runs")
        # Asserted as a bound rather than against the constant, which would follow it anywhere.
        # The retry loop only buys attempts if one attempt is short; at the driver's 30s
        # default a single attempt spends a fifth of the whole startup budget.
        self.assertLessEqual(selection, 10.0,
                             f"one attempt at reaching a server is given {selection}s, which is "
                             f"long enough that retrying stops being the point")

    def test_opening_a_socket_keeps_its_full_default(self):
        """
        The correction of a mistake, pinned so it is not made again.

        Lowering `connectTimeoutMS` alongside server selection looked consistent and was wrong.
        Server selection is what the retry loop drives, so shortening it buys attempts. Opening
        a socket is not retried by anything: the pool does it on demand, for every operation
        needing a connection, and the startup sequence needs several in parallel right after
        the ping succeeds.

        Observed when it was lowered: the ping was retried and answered on the third attempt,
        then index creation opened a new pool connection five seconds later, into the same
        unsettled network, and failed with a quarter of the headroom it used to have.
        """
        client = open_mongo_client("mongodb://compass_user:%s@node-1:27017/" % PASSWORD)
        connect_timeout = client.options.pool_options.connect_timeout
        self.assertEqual(
            20.0, connect_timeout,
            f"connectTimeoutMS is set to {connect_timeout}s rather than left at the driver's "
            f"20s default. The retry loop does not cover opening a socket, so this is headroom "
            f"taken from every operation in the startup sequence and given to nothing.")

    def test_a_query_that_is_already_running_is_not_cut_short(self):
        """Vector searches legitimately outlast anything that is right for a connection."""
        client = open_mongo_client("mongodb://compass_user:%s@node-1:27017/" % PASSWORD)
        self.assertIsNone(client.options.pool_options.socket_timeout)

    def test_a_caller_can_still_override(self):
        client = open_mongo_client("mongodb://node-1:27017/", serverSelectionTimeoutMS=1234)
        self.assertEqual(1.234, client.options.server_selection_timeout)

if __name__ == "__main__":
    unittest.main(verbosity=2)
