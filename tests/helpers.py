"""Shared test setup: a fresh in-memory company per test, and runtime files in a temp folder."""
import os
import tempfile
import warnings

warnings.simplefilter("ignore", ResourceWarning)  # tests leave in-memory databases to the garbage collector

_TMP = tempfile.mkdtemp(prefix="peopleops-tests-")
os.environ["PEOPLEOPS_VAR"] = _TMP          # Slack outbox, eval report etc. go here, not into the repo
os.environ["PEOPLEOPS_MODEL"] = "mock"       # tests never call a live model
os.environ.pop("SLACK_WEBHOOK_URL", None)

from peopleops import adapters, db, seed  # noqa: E402
from peopleops.context import Ctx  # noqa: E402

TMP = _TMP
SECRET = "test-secret"


def make_conn():
    conn = db.connect(":memory:")
    seed.seed(conn)
    return conn


def make_ctx(conn, user="E006"):
    """E002 Dana = People team, E003/E005 = managers, E006 Jordan and E007 Nadia = employees."""
    return Ctx.for_user(conn, user, adapters.build(conn))
