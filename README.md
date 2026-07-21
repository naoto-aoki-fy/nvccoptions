# nvccoptions

`nvccoptions` extracts the compiler and linker options used internally by the NVIDIA HPC SDK MPI C++ wrapper and writes them as reusable GNU Make configuration files.

The tool executes a small CUDA program through `mpicxx`, traces the resulting `execve` and `execveat` system calls, identifies the underlying `nvc++` invocations, and records their reusable compiler and linker arguments.

It also detects the Compute Capabilities of the visible NVIDIA GPUs and generates the corresponding `nvcc` `-gencode` options.

## Generated files

Running `make` produces the following files:

| File                | Description                                                                                                                                         |
| ------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------- |
| `config_vendor.mk`  | `CFLAGS_VENDOR`, `LDFLAGS_VENDOR`, and selected environment variables obtained from the traced `nvc++` invocations. |
| `config_gencode.mk` | `GENCODE_FLAGS` generated from the Compute Capabilities reported by `nvidia-smi`.                                                              |
| `config.mk`         | The combined contents of `config_vendor.mk` and `config_gencode.mk`.                                                                                |

`config_vendor.mk` defines variables such as:

```make
CFLAGS_VENDOR := ...
LDFLAGS_VENDOR := ...
```

It may also contain exported environment variables required by the detected NVIDIA HPC SDK or MPI configuration.

`config_gencode.mk` defines:

```make
GENCODE_FLAGS = -gencode=arch=compute_XX,code=sm_XX ...
```

One `-gencode` option is generated for each distinct Compute Capability visible on the system.

## Requirements

The configuration-generation environment requires:

* Linux
* GNU Make
* Python 3
* `strace`
* `unshare`, normally provided by `util-linux`
* NVIDIA HPC SDK
* An `mpicxx` command that eventually invokes `nvc++`
* `nvidia-smi` and at least one visible NVIDIA GPU for automatic generation of `config_gencode.mk`

The system must permit the following type of unprivileged user namespace:

```bash
unshare -Ur
```

Some containers, compute nodes, and hardened Linux installations disable unprivileged user namespaces. In that case, the trace commands in the supplied `Makefile` will fail unless the environment or command invocation is adjusted.

## Basic usage

Generate all configuration files:

```bash
make
```

This performs the following steps:

1. Compile `dummy.cu` through `mpicxx` while tracing process execution.
2. Link the resulting object through `mpicxx` while tracing process execution.
3. Convert the `strace` output into JSON Lines.
4. Extract the compile and link invocations of `nvc++`.
5. Generate `config_vendor.mk`.
6. Query the visible GPUs with `nvidia-smi`.
7. Generate `config_gencode.mk`.
8. Combine both fragments into `config.mk`.

Individual fragments can also be generated separately:

```bash
make config_vendor.mk
make config_gencode.mk
```

Remove generated files:

```bash
make clean
```

## Selecting the MPI compiler wrapper

The default MPI compiler wrapper is `mpicxx`. Override `MPICXX` when a different command or an absolute path is required:

```bash
make MPICXX=/path/to/nvidia/hpc_sdk/comm_libs/mpi/bin/mpicxx
```

The Python interpreter can be overridden in the same way:

```bash
make PYTHON=/path/to/python3
```

Additional options passed to the probe compilation or link command can be supplied through `CFLAGS` and `LDFLAGS`:

```bash
make \
    CFLAGS="-O2" \
    LDFLAGS="-cuda"
```

## Using the generated configuration

A downstream Makefile can include the generated configuration:

```make
include /path/to/config.mk
```

For example:

```make
NVCC ?= nvcc --forward-unknown-to-host-compiler

example.o: example.cu
	$(NVCC) $(CFLAGS_VENDOR) $(GENCODE_FLAGS) -c $< -o $@

example: example.o
	$(NVCC) $(LDFLAGS_VENDOR) $^ -o $@
```

The exact integration depends on the consuming build system. Review the generated vendor variables before adding them to an existing set of compiler or linker flags.

## GPU-less build environments

A build environment does not always have access to an NVIDIA GPU. This is common for login nodes, container image builders, CI runners, and cross-compilation hosts.

`config_gencode.mk` cannot be generated automatically when:

* `nvidia-smi` is unavailable;
* the NVIDIA driver is unavailable;
* no NVIDIA GPU is visible; or
* access to the GPU is blocked by the container or job configuration.

In such a setup, generate `config_gencode.mk` on another system that has access to the GPU architecture for which the application will be built, and then copy the generated file into the build environment.

Depending on the installation, it may also be necessary to generate `config_vendor.mk` on another system. For example, the GPU-less build host may not have an operational NVIDIA HPC SDK MPI wrapper, or its `mpicxx` environment may differ from the environment used on the target system.

A typical workflow is:

```bash
# On a representative environment:
make config_vendor.mk config_gencode.mk

# Copy both files to the GPU-less build environment:
scp config_vendor.mk config_gencode.mk build-host:/path/to/project/
```

On the build host, combine the copied fragments if `config.mk` is needed:

```bash
cat config_vendor.mk config_gencode.mk > config.mk
```

The environment used to generate these files should match the intended build or execution environment as closely as possible, including:

* NVIDIA HPC SDK version;
* MPI implementation and wrapper configuration;
* CUDA Toolkit version;
* host compiler and linker configuration; and
* target GPU Compute Capability.

`config_vendor.mk` may contain exported environment variables or installation paths from the machine on which it was generated. Inspect the file after copying it and remove or update values that are not valid on the build host.

## Intermediate files

The generation process creates the following intermediate files:

```text
dummy.o
strace_compile.txt
strace_link.txt
strace_compile.json
strace_link.json
```

The text files contain the raw `strace` output. The JSON files contain parsed `execve` and `execveat` records and can be useful when diagnosing missing or unexpected compiler options.

## When to regenerate the files

Regenerate `config_vendor.mk` after changing any of the following:

* NVIDIA HPC SDK version;
* MPI installation or `mpicxx` wrapper;
* compiler or linker configuration;
* relevant environment modules; or
* build environment paths.

Regenerate `config_gencode.mk` when the set of target GPU architectures changes.

## Limitations

* The supplied tracing workflow is Linux-specific.
* Only `nvc++` invocations are extracted.
* Compile invocations are recognized from `-c` and source files ending in `.c`, `.cpp`, or `.cu`.
* Link invocations are recognized from object files ending in `.o`.
* The generated configuration represents the observed wrapper behavior in the generation environment. It is not guaranteed to be portable to an unrelated NVIDIA HPC SDK, MPI, CUDA, or system configuration.
