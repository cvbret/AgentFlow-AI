class ExecutionLedgerError(RuntimeError):
    """Base execution-ledger failure; automatic retry is not authorized."""


class ExecutionIdentityConflict(ExecutionLedgerError):
    pass


class ExecutionReplayBlocked(ExecutionLedgerError):
    pass


class ExecutionPersistenceConflict(ExecutionLedgerError):
    pass
