<!-- ownership: kit -->
# Capture → Weave → Retrieve Tracer

`run.py` creates a temporary LBrain, captures a fictional Source, weaves it into a Wiki concept, retrieves the concept by its synthetic phrase, and runs the full validator. It deletes the temporary copy when finished and never writes to the active LBrain.

Run from the repository root:

```sh
python3 System/Kit/Examples/Tracer/run.py
```

Expected final line: `TRACE PASS: Capture -> Weave -> Retrieve`.
