# Evidence records

One JSON file per evaluated run: `<date>-<model>-<TEST>.json`, created by

```
python -m lord acceptance record --test T03 --model gemini-3.6-flash --transcript <conversation id> --notes "..."
```

The command prefills the deterministic facts from the working tree and the
session state (files touched, lines added and removed, new symbols, bloat
signal, LORD commands recorded, hook decisions, demo and oracle test
results, per-scenario checks) and leaves the human fields and the scores
blank. Fill `human`, `scores` (PASS / PARTIAL / FAIL / N/A per
`../SCORECARD.md`) and `final_verdict`, then commit the file.

What a record contains and what it must not contain:

- observable outputs and engineering evidence only: file names, counts,
  command names, hook decisions, test results, quotes of the agent's
  visible explanation;
- the transcript reference (conversation id or an exported file path
  outside the repository), never the transcript itself;
- no secrets, tokens, machine paths or hidden model reasoning.

`TEMPLATE.json` shows the shape. `tests/test_acceptance.py` validates every
committed record against it.

Reset between runs so records stay independent:

```
git checkout -- demo && git clean -fd demo
python -m lord index --rebuild
del .lord\session\activity.jsonl .lord\session\hooks.log     (PowerShell: Remove-Item .lord\session\*.jsonl, .lord\session\*.log)
```
