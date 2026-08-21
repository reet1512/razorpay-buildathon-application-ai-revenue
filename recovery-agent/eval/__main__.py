# Makes `python -m eval` redirect to the harness CLI.
from eval.harness import main

raise SystemExit(main())
