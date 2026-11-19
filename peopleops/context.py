"""The bundle of things a request needs: database, who is asking, and the adapters."""
from dataclasses import dataclass

from . import adapters, permissions


@dataclass
class Ctx:
    conn: object
    actor: dict      # the employee (or system) on whose behalf we act; set by the server, NEVER by the model
    adapters: object

    @classmethod
    def for_user(cls, conn, user_id, adapter_set=None):
        actor = permissions.get_employee(conn, user_id)
        if actor is None:
            raise KeyError(f"unknown user {user_id}")
        return cls(conn, actor, adapter_set or adapters.build(conn))
