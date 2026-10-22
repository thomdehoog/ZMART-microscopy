"""Remove the conda environment of the target acquisition analysis.

Removes ``ZMART--target_acquisition_for_coders--classical``. ``--dry-run``
lists it without removing anything.
"""

from __future__ import annotations

from zmart_analysis.environments import clean_workflow_envs

if __name__ == "__main__":
    clean_workflow_envs(workflow="target_acquisition_for_coders")
