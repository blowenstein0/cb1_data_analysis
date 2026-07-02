.PHONY: all download identify segment extract-text extract-structured eval load-db cost-report test

RUN = uv run python -m cb1.cli

# extract-text (vision OCR of scan-front files) must precede final
# segmentation of the scan era; segment re-runs automatically as OCR lands
all: download identify extract-text segment extract-structured load-db

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
