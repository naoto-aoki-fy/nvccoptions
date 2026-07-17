# nvccoptions

Utility for generating `nvcc` command line options used by `mpicxx` in the NVIDIA HPC SDK.

The scripts in this repository query the local compiler environment and GPU compute capabilities,
then print Makefile variable assignments for use with `nvcc`.

## Components

- `Makefile` - wrapper for the following Python scripts. Set `ENV` to select the compiler environment (`nvhpc` by default).
  - `nvcc_config.py` – Python script that generates `nvcc` option Makefile assignments.
  - `gencode_flags.py` – Python script that generates the `NVCC_GENCODE_FLAGS` Makefile assignment.

## Usage

Run the Makefile target to generate the config and write it to a config file:

```bash
make -s -C /path/to/nvccoptions | tee /path/to/config.mk
```

Select a compiler environment with the `ENV` variable. The default is `nvhpc`; use `cray` for the HPE Cray Programming Environment:

```bash
make -s -C /path/to/nvccoptions ENV=cray | tee /path/to/config.mk
```

Each invocation queries the current environment directly and prints Makefile assignments to
standard output. No generated results are cached.

The resulting variables can then be supplied to `nvcc` when compiling CUDA code outside of
`mpicxx`.
