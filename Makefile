.PHONY: all download identify segment extract-text extract-structured eval load-db cost-report test

RUN = uv run python -m cb1.cli

all: download identify segment extract-text extract-structured load-db

download:
	$(RUN) download

identify:
	$(RUN) identify

segment:
	$(RUN) segment

extract-text:
	$(RUN) extract-text

extract-structured:
	$(RUN) extract-structured

eval:
	$(RUN) eval

load-db:
	$(RUN) load-db

cost-report:
	$(RUN) cost-report

test:
	uv run pytest -q
