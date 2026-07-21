# nvccoptions

`nvccoptions` generates Makefile variables for compiling and linking CUDA code with `nvcc` while reusing the compiler and linker settings provided by an MPI compiler environment.

It supports:

* NVIDIA HPC SDK compiler environments
* HPE Cray Programming Environment
* Automatic generation of `-gencode` options from the NVIDIA GPUs visible on the system

The compiler configuration and GPU architecture configuration are generated separately, allowing them to be collected from different machines when necessary.

## Generated configuration

The default `make` target generates the following files:

| File                | Contents                                                                     |
| ------------------- | ---------------------------------------------------------------------------- |
| `config_vendor.mk`  | Compiler and linker options obtained from the selected compiler environment  |
| `config_gencode.mk` | `nvcc` code-generation options obtained from the locally visible NVIDIA GPUs |
| `config.mk`         | Combined contents of `config_vendor.mk` and `config_gencode.mk`              |

`config_vendor.mk` defines:

```make
CFLAGS_VENDOR = ...
LDFLAGS_VENDOR = ...
```

In strace mode, `config_vendor.mk` also exports each additional environment
variable that was passed to `nvc++` by the MPI compiler wrapper, using the
variable's original name:

```make
export NAME = value
```

`config_gencode.mk` defines:

```make
GENCODE_FLAGS = ...
```

## Requirements

Depending on which configuration file is being generated, the following tools are required:

* Python 3
* Make
* For `config_vendor.mk`:

  * NVIDIA HPC SDK environment with `mpicxx`, or
  * HPE Cray Programming Environment with `CC`
* For `config_gencode.mk`:

  * `nvidia-smi`
  * At least one visible NVIDIA GPU

The compiler environment and the GPU do not have to be available on the same machine.

## Basic usage

Clone the repository and run `make`:

```bash
git clone https://github.com/naoto-aoki-fy/nvccoptions.git
cd nvccoptions
make
```

The default compiler environment is `nvhpc`.

This generates:

```text
config_vendor.mk
config_gencode.mk
config.mk
```

### NVIDIA HPC SDK

For the NVIDIA HPC SDK environment:

```bash
make ENV=nvhpc
```

The following commands are queried by default:

```text
mpicxx -showme:compile
mpicxx -showme:link
```

To inspect the actual `nvc++` invocations made by `mpicxx`, use strace mode:

```bash
make ENV=nvhpc MODE=strace config_vendor.mk
```

This mode runs separate compile and link probes through the command configured
by `STRACE_WRAPPER_COMMAND`, which defaults to `mpicxx -cuda`:

```text
unshare -Ur strace -f -v -s 1073741823 -e trace=execve,execveat mpicxx -cuda ...
```

Override `STRACE_WRAPPER_COMMAND` when the compiler wrapper needs a different
command prefix. For example, HPE Cray environments can be inspected with:

```bash
make ENV=cray MODE=strace STRACE_WRAPPER_COMMAND=CC config_vendor.mk
```

It extracts arguments from detected `nvc++` `execve`/`execveat` calls according
to `strace-spec.md`, filters probe inputs and NVIDIA wrapper-only options, and
writes additional `nvc++` environment variables as exported Makefile variables
using their original names. The host must permit unprivileged `unshare -Ur` and
provide `strace`.

### HPE Cray Programming Environment

For the HPE Cray Programming Environment:

```bash
make ENV=cray
```

The following commands are queried:

```text
CC --cray-print-opts=cflags
CC --cray-print-opts=libs
```

## Generating each configuration separately

The vendor and GPU configurations can be generated independently.

Generate only the compiler and linker configuration:

```bash
make ENV=nvhpc config_vendor.mk
```

or:

```bash
make ENV=cray config_vendor.mk
```

Generate only the GPU architecture configuration:

```bash
make config_gencode.mk
```

After both files are available, combine them:

```bash
rm -f config.mk
make config.mk
```

The resulting `config.mk` can be included from another Makefile.

## GPU-less build environments

A build environment may not have an NVIDIA GPU or a working `nvidia-smi` installation. It may also lack the compiler environment that will ultimately be used.

In that case, generate the configuration files on suitable systems and copy them into the build environment.

For example:

1. Generate `config_vendor.mk` in an environment that provides the same compiler and MPI configuration as the actual build:

   ```bash
   make ENV=nvhpc config_vendor.mk
   ```

   or:

   ```bash
   make ENV=cray config_vendor.mk
   ```

2. Generate `config_gencode.mk` on a machine with NVIDIA GPUs representative of the target system:

   ```bash
   make config_gencode.mk
   ```

3. Copy both files to the GPU-less build environment:

   ```text
   config_vendor.mk
   config_gencode.mk
   ```

4. Create the combined configuration:

   ```bash
   rm -f config.mk
   make config.mk
   ```

The two files may be generated on different machines. `config_vendor.mk` is specific to the compiler and MPI environment, while `config_gencode.mk` is specific to the GPU compute capabilities detected by `nvidia-smi`.

Regenerate the files whenever the compiler environment, MPI installation, or target GPU architecture changes.

## Using the generated configuration

Include `config.mk` from your project's Makefile:

```make
include /path/to/nvccoptions/config.mk

NVCC ?= nvcc --forward-unknown-to-host-compiler

kernel.o: kernel.cu
	$(NVCC) $(CFLAGS_VENDOR) $(GENCODE_FLAGS) -c $< -o $@

example: kernel.o
	$(NVCC) $^ $(LDFLAGS_VENDOR) -o $@
```

The variables serve the following purposes:

| Variable        | Purpose                                                                |
| --------------- | ---------------------------------------------------------------------- |
| `CFLAGS_VENDOR` | Compiler options reported by the selected compiler environment         |
| `LDFLAGS_VENDOR` | Original linker options reported by the selected compiler environment  |
| exported original environment names | Additional `nvc++` environment variables from strace mode |
| `GENCODE_FLAGS` | GPU architecture options such as `-gencode=arch=compute_80,code=sm_80` |

## GPU architecture detection

`gencode_flags.py` obtains compute capabilities using:

```bash
nvidia-smi --query-gpu=compute_cap --format=csv,noheader
```

Duplicate compute capabilities are removed, and one `-gencode` option is generated for each detected architecture.

For example:

```make
GENCODE_FLAGS = -gencode=arch=compute_80,code=sm_80 -gencode=arch=compute_90,code=sm_90
```

Only architectures visible on the machine where `config_gencode.mk` is generated are included. Edit `GENCODE_FLAGS` manually when additional target architectures are required.

## Regenerating configuration

Generated configuration files remain in the repository directory and are reused by Make.

To regenerate all files:

```bash
make clean
make ENV=nvhpc
```

or:

```bash
make clean
make ENV=cray
```

This is especially important when changing `ENV`, switching compiler installations, or generating options for different GPUs.

To remove all generated configuration files:

```bash
make clean
```

## Running the scripts directly

The underlying Python scripts can also be run directly.

Generate the NVIDIA HPC SDK compiler configuration:

```bash
python3 nvcc_config.py --environment nvhpc
```

Generate the HPE Cray compiler configuration:

```bash
python3 nvcc_config.py --environment cray
```

Generate GPU code-generation flags:

```bash
python3 gencode_flags.py
```
