# nvccoptions

Utility for generating `nvcc` command line options used by `mpicxx` in the NVIDIA HPC SDK.

The scripts in this repository query the local compiler environment and GPU compute capabilities,
then print Makefile variable assignments for use with `nvcc`.

## Components

- `gen_config.sh` - Bash wrapper for following python scripts
  - `gen_nvccoptions.py` – Python script that generates `nvcc` option Makefile assignments.
  - `gen_gencode_flags.py` – Python script that generates the `NVCC_GENCODE_FLAGS` Makefile assignment.

## Usage

Run the helper script to generate and have it written to a config file:

```bash
/path/to/gen_config.sh | tee /path/to/config.mk
```

Each invocation queries the current environment directly and prints Makefile assignments to
standard output. No generated results are cached.

The resulting variables can then be supplied to `nvcc` when compiling CUDA code outside of
`mpicxx`.
