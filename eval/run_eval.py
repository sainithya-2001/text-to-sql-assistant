"""Thin wrapper so `python eval/run_eval.py ...` works; see text_to_sql/eval_cli.py (`t2s eval`)."""

import sys

from text_to_sql.eval_cli import main

if __name__ == "__main__":
    sys.exit(main())
