"""Laya's drafting lessons, step 4: laya-train, run from Laya's own env, with its evaluation passes cut from 16 items
at a time to 1. They run in full precision, about 3 GB an item on RotomArena's longer states (battle states run to
~3.4K tokens), so 16 spill far past a 16 GB card; training itself needs under 3 GB. Same arguments as laya-train:
  D:/docs/assets/generator/engines/laya/.venv/Scripts/python.exe scripts/laya/train.py --data ... --out ..."""
import sys

import laya.train
from laya.train_cli import main

_records = laya.train.calibration_records


def one_at_a_time(*args, **kwargs):
    kwargs["batch_size"] = 1
    return _records(*args, **kwargs)


laya.train.calibration_records = one_at_a_time
print("evaluation passes: 1 item at a time", flush=True)
sys.exit(main())
