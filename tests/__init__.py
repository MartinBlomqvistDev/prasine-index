# Test suite for the Prasine Index pipeline. Unit tests cover the Pydantic
# model layer (validation logic, field constraints, model validators), the
# retry and error boundary infrastructure, and the logger ContextVar wiring.
# Integration tests are kept separate and require a running PostgreSQL instance.
