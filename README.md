# nvccoptions

Utility for capturing the `nvcc` command line options used by `mpicxx` in the NVIDIA HPC SDK.

The scripts in this repository run `mpicxx` with a lightweight shim and record the options that
would normally be forwarded to `nvcc`.  The captured options are written to `nvccoptions.txt`
for later reuse.

## Components

- `gen_config.sh` - Bash wrapper for following python scripts
  - `gen_nvccoptions.py` – Python script that generate `nvcc` options and caches the result.
  - `gen_gencode_flags.py` – Python script that generate NVCC_GENCODE_FLAGS and caches the result.

## Usage

Run the helper script to generate and have it written to a config file:

```bash
/path/to/gen_config.sh | tee /path/to/config.mk
```

On the first run the script calls `mpicxx dummy.cu` to collect the options and writes them to
`nvccoptions.txt`. Subsequent invocations reuse the cached file and simply echo the stored
options to standard output.

The resulting option string can then be supplied to `nvcc` when compiling CUDA code outside of
`mpicxx`.
