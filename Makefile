.PHONY: help run test test-scanner test-web scan rescore lint live digest

help:            ## list targets
	@grep -E '^[a-z-]+:.*##' Makefile | sed 's/:.*##/\t/'

run:             ## start the web app on http://127.0.0.1:8000
	./scripts/start.sh

test: test-scanner test-web   ## run every test suite

test-scanner:    ## scanner, matching, sources: offline, no network
	cd jobhunt && python tests/test_pipeline.py

test-web:        ## Django app tests (temporary database)
	cd django_project && python manage.py test

scan:            ## fetch, score and store jobs (no Google Sheets write)
	cd jobhunt && python -m src.run --dry-run

rescore:         ## re-score stored jobs with the current resume and preferences (no network)
	cd jobhunt && python -m src.run --rescore

live:            ## audit every real job source over the network
	cd jobhunt && python live_check.py

digest:          ## what's new and worth your time
	cd jobhunt && python -m src.digest --days 1

lint:            ## syntax / undefined-name check (same as CI)
	ruff check .
