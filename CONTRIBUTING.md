# Contributing

Issues and pull requests are welcome. Original contributions use the project's
0BSD license. Do not contribute Valve source, proprietary assets, external
binaries, credentials, machine settings or private test logs.

Install requirements.lock in a Python environment, ensure FFmpeg is present, and
run `python -m unittest discover -p 'test_*.py' -v`.

Keep tests independent of Steam accounts and private paths. Document live engine
checks separately with precise scope. Add a regression test for each fix. Keep
hash checks, backups, loopback defaults, job cancellation, and the distinction
between a requested operation and successful verification. New tools need type
annotations, accurate docstrings and an updated tool reference.
