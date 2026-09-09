class ExecutionLedgerError(RuntimeError):
    """Base execution-ledger failure; automatic retry is not authorized."""


class ExecutionIdentityConflict(ExecutionLedgerError):
    pass


class ExecutionReplayBlocked(ExecutionLedgerError):
    pass


class ExecutionPersistenceConflict(ExecutionLedgerError):
    pass


class ExecutionPersistenceUncertain(ExecutionLedgerError):
    """Local ledger durability is unconfirmed; distinct from an external UNKNOWN.

    Stop continuation and re-read durable evidence through explicit recovery.
    """
