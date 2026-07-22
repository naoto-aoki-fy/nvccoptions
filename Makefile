ENV ?= nvhpc
MODE ?= wrapper
PYTHON ?= python3
CC ?= cc
CFLAGS ?= -O2 -Wall -Wextra

ifeq ($(MODE),seccomp)
CONFIG_VENDOR_DEPS := libseccomp_exec_logger.so
endif

.PHONY: all
all: config.mk

libseccomp_exec_logger.so: seccomp_exec_logger.c
	$(CC) $(CFLAGS) -fPIC -shared -o $@ $<

config.mk: config_vendor.mk config_gencode.mk
	cat $^ > $@
	cat $@

config_vendor.mk: $(CONFIG_VENDOR_DEPS)
	$(PYTHON) $(CURDIR)/nvcc_config.py --environment $(ENV) --mode $(MODE) --strace-wrapper-command "$(MPICXX)" > $@
	cat $@

config_gencode.mk:
	$(PYTHON) $(CURDIR)/gencode_flags.py > $@

.PHONY: clean
clean:
	$(RM) config_vendor.mk config_gencode.mk config.mk libseccomp_exec_logger.so
