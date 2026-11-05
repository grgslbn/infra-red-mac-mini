#!/bin/bash
# sleepwatcher -s : system is about to sleep. Runs synchronously; keep it quick.
exec "$(cd "$(dirname "$0")/.." && pwd)/bin/heater" hook sleep
