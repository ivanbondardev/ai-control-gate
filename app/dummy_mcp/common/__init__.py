"""Shared runtime for the dummy MCP services.

Nothing in this package reads the Gate database, and nothing in it trusts a client-supplied
policy: a dummy enforces its own data boundaries (ownership, business invariants, schema) while
the Gate owns the customer policy.
"""
