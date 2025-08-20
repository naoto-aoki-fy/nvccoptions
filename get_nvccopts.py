#!/usr/bin/env python3

import sys
import os
import subprocess
import json
import shlex

nvcc_options_fn = os.path.dirname(__file__) + "/nvccoptions.txt"

if os.path.exists(nvcc_options_fn):
    with open(nvcc_options_fn, "rb") as fp:
        sys.stdout.buffer.write(fp.read())
    sys.exit(0)

path_saved = os.environ["PATH"]
path_new = os.getcwd() + "/fake_nvcc:" + path_saved
os.environ["PATH"] = path_new

mpicxx_output = subprocess.check_output(("mpicxx", "main.cu"))
nvcc_argv = json.loads(mpicxx_output)

assert nvcc_argv[0].endswith("/nvc++")
assert nvcc_argv[1] == "main.cu"

nvcc_options : list = []
for word in nvcc_argv[2:]:
    if word == "-pthread":
        continue

    if word.startswith("-Wl,"):
        parts = word.split(",")
        for part in parts[1:]:
            if part:
                nvcc_options.extend(["-Xlinker", part])
    else:
         nvcc_options.append(word)


nvcc_options_join = shlex.join(nvcc_options) + "\n"
with open(nvcc_options_fn, "wt") as fp:
    fp.write(nvcc_options_join)

sys.stdout.write(nvcc_options_join)
