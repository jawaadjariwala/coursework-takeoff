#!/bin/sh
# Build the code tour PDF.  Output: docs/build/code-tour.pdf
set -e
cd "$(dirname "$0")"
mkdir -p build
tectonic -X compile code-tour.tex --outdir build
echo "built: $(pwd)/build/code-tour.pdf"
