"""Opt-in, finite-domain collective workflow integration.

Importing this package neither opens companion stores nor runs a worker.
"""

from oasg.collective.wire import Contract, Execution, Scope, Source, TaskBinding

__all__ = ["Contract", "Execution", "Scope", "Source", "TaskBinding"]
