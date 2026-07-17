ENV ?= nvhpc
PYTHON ?= python3

.PHONY: config
config:
	@$(PYTHON) $(CURDIR)/gencode_flags.py
	@$(PYTHON) $(CURDIR)/nvcc_config.py --environment $(ENV)
