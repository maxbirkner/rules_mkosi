import os

import pefile

with open(os.environ["MKOSI_PEFILE_PROBE"], "w", encoding="utf-8") as probe:
    probe.write(pefile.__version__)
