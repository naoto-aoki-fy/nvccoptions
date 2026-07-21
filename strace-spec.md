# `nvc++` Argument and Environment Variable Extraction Specification

## 1. Purpose

Execute the NVIDIA HPC SDK MPI C++ compiler wrapper and obtain the compilation arguments, linking arguments, and environment variables passed to the internally invoked `nvc++` process.

## 2. Inspection Procedure

Perform compilation and linking separately for a minimal CUDA C++ program using the MPI compiler wrapper.

Observe the processes created during execution. For each process whose executable basename or `argv[0]` basename is `nvc++`, collect the following:

* Command-line arguments
* Environment variables passed to the process

## 3. Observation Using `unshare` and `strace`

The current implementation executes the target command in the following form:

```bash
unshare -Ur \
  strace -f -v -s 1073741823 \
  -e trace=execve,execveat \
  <MPI compiler wrapper and arguments>
```

The purpose of each option is as follows.

| Option                     | Purpose                                                                     |
| -------------------------- | --------------------------------------------------------------------------- |
| `unshare -U`               | Execute the command in a new user namespace                                 |
| `unshare -r`               | Map the current user to root within the namespace                           |
| `strace -f`                | Trace child processes as well                                               |
| `strace -v`                | Suppress abbreviation of arrays and structures                              |
| `strace -s 1073741823`     | Effectively disable truncation of argument and environment variable strings |
| `-e trace=execve,execveat` | Trace only process execution-related system calls                           |

Parse the `strace` output to extract the execution path, argument array, and environment variable array for each `execve` and `execveat` call.

`strace` may emit split system calls such as the following, which shall be reconstructed into a single execution record.

```text
execve(...) <unfinished ...>
<... execve resumed> ...
```

Since `strace` normally writes trace output to standard error, it shall be captured separately from the standard output of the target program.

Using `unshare` and `strace` is **not** a mandatory implementation requirement. Any alternative observation method may be used, provided that it can obtain equivalent argument arrays and environment variables.

However, in environments using the current approach, unprivileged users must be permitted to execute:

```bash
unshare -Ur
```

In containers, compute nodes, or Linux environments with hardened security settings, unprivileged user namespaces may be disabled.

## 4. Classification of Compilation and Linking

Each captured `nvc++` command shall be classified according to its arguments.

### Compilation

A command is considered a compilation if it contains any of the following:

* `-c`
* An argument ending with `.c`, `.cpp`, or `.cu`

### Linking

A command is considered a linking operation if it contains an argument ending with `.o`.

If both conditions apply, classify the command as a compilation.

## 5. Argument Extraction

Do not include `argv[0]`, which represents the executable, in the extracted result.

### Exclude from Compilation Arguments

* `-c`
* Input files ending with `.c`, `.cpp`, or `.cu`
* `-cuda`
* `-acc`
* `-tp` and its value
* `-gpu` and its value

### Exclude from Linking Arguments

* Input files ending with `.o`
* `-cuda`
* `-acc`
* `-tp` and its value
* `-gpu` and its value

Exclude both forms of these options:

* `-tp=value`, `-gpu=value`
* `-tp value`, `-gpu value`

All remaining arguments shall be extracted while preserving both their original order and argument boundaries.

If multiple `nvc++` commands are detected, concatenate the extracted results in detection order.

## 6. Environment Variable Extraction

Collect the environment variables passed to each selected `nvc++` process.

If a variable with the same name and value exists in the execution environment of the extraction process itself, omit it from the output.

Always exclude the following variables:

* `HOME`
* `HOSTNAME`
* `PWD`
* `SHLVL`
* `_`
* `HFI_NO_BACKTRACE`
* `IPATH_NO_BACKTRACE`

Also exclude variables whose names begin with:

* `BASH_FUNC_`
* `_LMFILES_`
* `PJM_`

Ignore any entries whose names are not valid environment variable names.

If the same variable is detected in multiple `nvc++` processes, use the value from the last occurrence.

## 7. Extraction Results

The implementation shall produce at least the following:

* The extracted `nvc++` compilation argument list
* The extracted `nvc++` linking argument list
* Additional environment variables required to execute `nvc++`

Arguments shall be preserved in a representation that maintains argument boundaries, even when they contain whitespace or special characters.

## 8. Warnings and Errors

Treat the following conditions as errors:

* The inspection compilation or linking step fails.
* Process information cannot be collected or parsed.
* The collected data has an invalid format.
* An implementation that depends on `unshare` or `strace` cannot execute them.

If no `nvc++` command corresponding to compilation or linking is found, issue a warning. The corresponding extracted argument list may be empty.

## 9. Constraints

* The target operating system is Linux.
* The target compiler is `nvc++`.
* Compilation inputs are `.c`, `.cpp`, and `.cu` files.
* Linking inputs are `.o` files.
* The extracted results depend on the NVIDIA HPC SDK version, MPI wrapper, environment variables, and installation configuration present during inspection.

## 10. Implementation-Defined Behavior

The following aspects are implementation-defined and may be chosen freely:

* Whether to use `unshare` and `strace`
* How processes and commands are observed
* The programming language used
* The intermediate data format
* The module organization
* The format used to store extracted results
* The format of logs and diagnostic information
