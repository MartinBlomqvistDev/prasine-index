# Evaluation harness for the Prasine Index pipeline. Contains the golden
# dataset of 20 known greenwashing cases with expected verdicts and scores,
# and the runner that executes the full pipeline against each case and reports
# accuracy metrics. Runs automatically on every pipeline change as part of
# the LLMOps quality gate.
