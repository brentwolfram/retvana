PYTHON ?= .venv/bin/python

# The host Data_Dir mounted into the container at /data. Defaults to the platformdirs user data
# directory for retvana (the same place the local app saves), so both share one plan.json.
ifeq ($(strip $(RETVANA_HOST_DATA_DIR)),)
RETVANA_HOST_DATA_DIR := $(shell $(PYTHON) -c "import platformdirs; print(platformdirs.user_data_dir('retvana', appauthor=False))" 2>/dev/null)
endif
export RETVANA_HOST_DATA_DIR

.PHONY: run up down restart rebuild logs status verify data-dir

run:       ## run the app on the host venv -> http://localhost:8501
	$(PYTHON) -m streamlit run app.py
up: data-dir      ## start the retvana container in the background -> http://localhost:8501
	docker compose up -d
down:      ## stop and remove the retvana container
	docker compose down
restart:   ## restart without rebuilding
	docker compose restart
rebuild: data-dir ## rebuild the retvana image after code changes, then start
	docker compose up -d --build
logs:      ## follow the app logs
	docker compose logs -f
status:    ## container state and health
	docker compose ps
verify:    ## run every check and the smoke test on the host venv (not in the container)
	$(PYTHON) scripts/verify.py
data-dir:  ## create the host data directory the container mounts
	@test -n "$(RETVANA_HOST_DATA_DIR)" || { echo "RETVANA_HOST_DATA_DIR is not set and $(PYTHON) could not compute it (is the venv installed?)"; exit 1; }
	@mkdir -p "$(RETVANA_HOST_DATA_DIR)"
