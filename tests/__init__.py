# Yuzu Companion test suite.
#
# Stage 1 starts with smoke tests for the pure helpers that don't need a
# live PostgreSQL database. Run with:
#
#     pytest -q
#
# Future stages will add fixtures for a transient DB once we have a
# docker-compose target for tests on Termux.
