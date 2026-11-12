# Regression cases for the Prasine Index pipeline, and their runner. The 20
# cases are climate claims of named companies, each with the label and score
# range expected under version 1 of the method; several expected labels were
# set to match the pipeline's own output at the time. A case is not a judgement
# of the company or its claim. The runner reports how many cases match their
# expected label and score range, the time per case and the tokens used; it
# does not measure accuracy. It runs by hand or from the manual Eval workflow;
# it does not run on every push.
