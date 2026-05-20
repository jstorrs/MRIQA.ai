"""DEPRECATED — this file has moved to project_root/streamlit_app.py

Having an entry script named ``app.py`` inside the ``app/`` package made
Python mistake the script for the package (``ModuleNotFoundError: 'app'
is not a package``). The Streamlit entry point now lives at the project
root as ``streamlit_app.py``.

If you somehow run this file directly it will print a helpful message.
"""

import sys


def _explain_and_exit() -> None:
    sys.stderr.write(
        "\nMRIQA.ai entry point has moved.\n"
        "Run:\n"
        "    streamlit run streamlit_app.py\n"
        "from the project root, or just double-click 'Launch MRIQA.command'.\n\n"
    )
    sys.exit(1)


_explain_and_exit()
