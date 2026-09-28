# jobhunt: the scanner and intelligence package

The Python package (`src/`) behind the web app in `../django_project`. See the [top-level README](../README.md) and
[docs/ARCHITECTURE.md](../docs/ARCHITECTURE.md).

```bash
python -m src.run --dry-run        # fetch, score, store (add --digest to print what's new)
python -m src.run --rescore        # re-score stored jobs, no network
python -m src.digest --days 1      # new roles worth your time (Markdown)
python live_check.py [--source tt] # audit real sources
python tests/test_pipeline.py      # offline test suite
python -m src.cover_letter --interactive
```

Config lives in `config/` (created from the `*.example*` templates on first run, git-ignored). Output (database, JSON/CSV,
letters) goes to `output/` (git-ignored).
