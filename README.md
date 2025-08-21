# nvccoptions

Utility for capturing the `nvcc` command line options used by `mpicxx` in the NVIDIA HPC SDK.

The scripts in this repository run `mpicxx` with a lightweight shim and record the options that
would normally be forwarded to `nvcc`.  The captured options are written to `nvccoptions.txt`
for later reuse.

## Components

- `get_nvccopts.py` – Python script that drives the discovery process and caches the result.
- `get_nvccopts.sh` – Convenience wrapper that executes the Python helper.
- `fake_nvc++` – Minimal shim compiler used to intercept the arguments passed by `mpicxx`.

## Usage

Run the helper script to generate and print the `nvcc` options:

```bash
./get_nvccopts.sh
```

On the first run the script calls `mpicxx dummy.cu` to collect the options and writes them to
`nvccoptions.txt`. Subsequent invocations reuse the cached file and simply echo the stored
options to standard output.

The resulting option string can then be supplied to `nvcc` when compiling CUDA code outside of
`mpicxx`.
