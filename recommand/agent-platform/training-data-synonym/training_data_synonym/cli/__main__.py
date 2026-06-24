"""Allow `python -m training_data_synonym.cli` to invoke main()."""

import sys

from . import main

if __name__ == "__main__":
    sys.exit(main())
