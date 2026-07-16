#!/bin/bash

set -eo pipefail 

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

environment="nvhpc"

parsed=$(
  getopt \
    --options e:h \
    --longoptions environment:,help \
    --name "$0" \
    -- "$@"
) || exit 1

eval set -- "$parsed"

while true; do
  case "$1" in
    -e|--environment)
      environment="$2"
      shift 2
      ;;
    -h|--help)
      echo "Usage: $0 [-e ENVIRONMENT] [--environment ENVIRONMENT]" 1>&2
      exit 0
      ;;
    --)
      shift
      break
      ;;
    *)
      echo "Internal error: unexpected option '$1'" >&2
      exit 1
      ;;
  esac
done

set -x
python3 "${SCRIPT_DIR}/gen_gencode_flags.py" --mode make
python3 "${SCRIPT_DIR}/gen_nvccoptions.py" --mode make --environment "$environment"
