# Contributing

1. Keep the standard-library-only baseline (`Python 3.10+`, `git`).
2. Run `python -m unittest discover tests` before a commit.
3. Repair defects with the smallest safe patch and add a regression test.
4. Use Conventional Commits and never force-push.
5. Edit the shipped source in AIKit first, then `python aikit.py reforge repo sync --direction push`
   to publish it here; use `--direction pull` for a fix made in this repository.
