#!/usr/bin/env python3

import sys
import os
import subprocess
import json
import shlex
import socket

def main():

    repo_dir = os.path.dirname(__file__)
    hostname = socket.gethostname()
    nvcc_options_fn = os.path.join(repo_dir, f"nvccoptions_{hostname}.txt")
    fake_nvcxx = os.path.join(repo_dir, "fake_nvc++")
    dummy_cu = "dummy.cu"

    if os.path.exists(nvcc_options_fn):

        with open(nvcc_options_fn, "rb") as fp:
            nvcc_options_join = fp.read()

    else:

        environ = dict(os.environ)
        environ["OMPI_CXX"] = fake_nvcxx

        mpicxx_output = subprocess.check_output(("mpicxx", dummy_cu), env=environ)
        nvcc_argv = json.loads(mpicxx_output)

        assert nvcc_argv[0] == fake_nvcxx
        assert nvcc_argv[1] == dummy_cu

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

        nvcc_options_join = os.fsencode(shlex.join(nvcc_options) + "\n")
        with open(nvcc_options_fn, "wb") as fp:
            fp.write(nvcc_options_join)

    sys.stdout.buffer.write(nvcc_options_join)

if __name__ == '__main__':
    main()