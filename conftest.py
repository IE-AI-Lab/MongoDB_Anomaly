"""Pytest root conftest.

Its mere presence makes pytest treat this directory as the rootdir and prepend
it to sys.path, so tests can import the top-level modules (`severity_engine`)
and the `ingestor_service` package without an install step.
"""
