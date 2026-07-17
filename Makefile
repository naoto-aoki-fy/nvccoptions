MPICXX ?= mpicxx
CFLAGS ?=
LDFLAGS ?= -cuda
PYTHON ?= python3

.PHONY: all clean

all: config.mk

strace_compile.txt dummy.o: dummy.cu
	unshare -Ur strace -f -v -s 1073741823 \
		-e trace=execve,execveat \
		$(MPICXX) $(CFLAGS) -c $< 2> $@

strace_link.txt: dummy.o
	unshare -Ur strace -f -v -s 1073741823 \
		-e trace=execve,execveat \
		$(MPICXX) $(LDFLAGS) $< 2> $@

strace_compile.json: strace_compile.txt strace_exec_to_json.py
	$(PYTHON) strace_exec_to_json.py < $< > $@

strace_link.json: strace_link.txt strace_exec_to_json.py
	$(PYTHON) strace_exec_to_json.py < $< > $@

config_vendor.mk: strace_compile.json strace_link.json nvcc_config.py
	$(PYTHON) nvcc_config.py \
		strace_compile.json \
		strace_link.json > $@
	cat $@

config_gencode.mk:
	$(PYTHON) gencode_flags.py > $@
	cat $@

config.mk: config_vendor.mk config_gencode.mk
	cat config_vendor.mk config_gencode.mk > $@

clean:
	$(RM) -f dummy.o \
		strace_compile.txt strace_link.txt \
		strace_compile.json strace_link.json \
		config.mk config_vendor.mk config_gencode.mk
