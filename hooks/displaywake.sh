#!/bin/bash
# sleepwatcher -W : display woke up = a real user wake (dark wakes / Power Nap don't light the display).
# Runs in the background so sleepwatcher isn't blocked while we wait for Wi-Fi.
"$(cd "$(dirname "$0")/.." && pwd)/bin/heater" hook display-wake >/dev/null 2>&1 &
