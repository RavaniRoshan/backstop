# Wedge test fixture

A small Python project used by the Wedge multi-agent diff tool. Run it from
this directory:

```bash
wedge run task.yaml
```

It runs 3 isolated Anthropic agents against the `src/main.py` module, asks each
to refactor the standalone functions into a class, and diffs the resulting
patches. `tests/test_main.py` verifies behavior is preserved.
