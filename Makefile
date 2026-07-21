ENV ?= nvhpc
MODE ?= wrapper
STRACE_WRAPPER_COMMAND ?= mpicxx -cuda
PYTHON ?= python3

.PHONY: all
all: config.mk

config.mk: config_vendor.mk config_gencode.mk
	cat $^ > $@
	cat $@

config_vendor.mk:
	$(PYTHON) $(CURDIR)/nvcc_config.py --environment $(ENV) --mode $(MODE) --strace-wrapper-command "$(STRACE_WRAPPER_COMMAND)" > $@
	cat $@

config_gencode.mk:
	$(PYTHON) $(CURDIR)/gencode_flags.py > $@

.PHONY: clean
clean:
	$(RM) config_vendor.mk config_gencode.mk config.mk
