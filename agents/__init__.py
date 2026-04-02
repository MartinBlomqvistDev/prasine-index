# Agent implementations for the Prasine Index pipeline. Each module in this
# package contains a single agent class responsible for one stage of the
# 7-step claim verification workflow. Agents communicate exclusively through
# Pydantic v2 models defined in the models package; no raw strings or untyped
# dicts cross agent boundaries.
