#!/usr/bin/env bash
# Builds the saved FPL API data (invented clubs and players) into ./fpl-data.
set -eu
python3 "$(dirname "$0")/../../tests/make_eval_fixture.py" fpl-data
