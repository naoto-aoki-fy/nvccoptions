ENV ?= nvhpc
PYTHON ?= python3

.PHONY: all
all: config.mk

config.mk: config_vendor.mk config_gencode.mk
	cat $^ > $@

config_vendor.mk:
	$(PYTHON) $(CURDIR)/nvcc_config.py --environment $(ENV) | tee $@

config_gencode.mk:
	$(PYTHON) $(CURDIR)/gencode_flags.py | tee $@
