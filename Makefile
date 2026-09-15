.PHONY: help install install-audio test lint check-key tunnel serve provision \
        preflight smoke rescore check-fixtures smoke-voice run-text run-full report synthetic clean

PY := .venv/bin/python
PIP := uv pip install --python .venv/bin/python

help:
	@grep -E '^[a-z-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

install: ## create venv and install the harness
	uv venv --python 3.12
	$(PIP) -e ".[dev,judge]"
	@echo "\nnext: cp .env.example .env && edit it (see docs/retell-setup.md)"

install-audio: ## add the voice channel (playwright + chromium)
	$(PIP) -e ".[audio]"
	$(PY) -m playwright install chromium

test: ## run the scorer test suite (no API key needed)
	$(PY) -m pytest tests/ -v

lint:
	$(PY) -m ruff check harness agent tests scripts

check-key: ## verify RETELL_API_KEY works
	@$(PY) -c "from dotenv import load_dotenv; load_dotenv(); \
	from harness.retell_client import RetellClient; \
	c=RetellClient(); a=c.list_agents(); \
	print(f'key OK — {len(a)} agent(s) on this account')"

tunnel: ## expose the clinic server publicly (leave running)
	cloudflared tunnel --url http://localhost:8000

serve: ## run the clinic tool server on :8000 (leave running)
	$(PY) -m uvicorn agent.clinic_server:app --port 8000

provision: ## create/update the 4 agents. usage: make provision URL=https://xxx.trycloudflare.com
	@test -n "$(URL)" || (echo "usage: make provision URL=https://xxx.trycloudflare.com"; exit 1)
	$(PY) -m agent.provision --tool-url $(URL) $(if $(UPDATE),--update,)

check-fixtures: ## verify every caller WAV is actually audible
	$(PY) scripts/check_fixtures.py

preflight: ## cheap setup checks before spending on a batch — run this first
	$(PY) -m harness.preflight

smoke: ## one cheap text run against the naive agent
	$(PY) -m harness.runner --scenario s01_happy_path --arms naive --channels text --repeats 1 --label smoke

smoke-voice: ## one real web call — first thing to try after install-audio
	$(PY) -m harness.runner --scenario s01_happy_path --arms naive --channels voice --repeats 1 --label smoke-voice

run-text: ## full text ablation (cheap)
	$(PY) -m harness.runner --arms naive hardened --channels text --repeats 3 --label text-ablation

run-full: ## full 2x2 ablation — costs real credits, check the estimate first
	$(PY) -m harness.runner --arms naive hardened --channels text voice --repeats 3 --label full-ablation

rescore: ## re-score a finished run with the current scorer (free). usage: make rescore DIR=runs/... [WRITE=1]
	@test -n "$(DIR)" || (echo "usage: make rescore DIR=runs/<dir> [WRITE=1]"; exit 1)
	$(PY) -m harness.rescore $(DIR) $(if $(WRITE),--write,)

report: ## render a run directory. usage: make report DIR=runs/2026...
	@test -n "$(DIR)" || (echo "usage: make report DIR=runs/<dir>"; exit 1)
	$(PY) -m harness.report $(DIR)

synthetic: ## regenerate the fabricated example run (no API key needed)
	$(PY) scripts/make_synthetic_run.py
	$(PY) -m harness.report runs/_synthetic_example

clean:
	rm -rf .pytest_cache .ruff_cache **/__pycache__
