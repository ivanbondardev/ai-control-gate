"""Dummy MCP services: independent synthetic backends with their own durable state.

Each service is a separate MCP server with its own SQLite volume. The Gate is the only network
client. No service reaches the Gate database, the internet or another service.
"""
__all__ = ['common', 'documents', 'outbox', 'tickets']
