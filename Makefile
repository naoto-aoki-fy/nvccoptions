ENV ?= nvhpc
MODE ?= wrapper
PYTHON ?= python3
CC ?= cc
CFLAGS ?= -O2 -Wall -Wextra


.PHONY: all
all: config.mk

libseccomp_exec_logger.so: seccomp_exec_logger.c
	$(CC) $(CFLAGS) -fPIC -shared -o $@ $<

config.mk: config_vendor.mk config_gencode.mk
	cat $^ > $@
	cat $@

config_vendor.mk:
	$(PYTHON) $(CURDIR)/nvcc_config.py --environment $(ENV) --mode $(MODE) --strace-wrapper-command "$(MPICXX)" > $@
	cat $@

config_gencode.mk:
	$(PYTHON) $(CURDIR)/gencode_flags.py > $@

.PHONY: clean
clean:
	$(RM) config_vendor.mk config_gencode.mk config.mk libseccomp_exec_logger.so
