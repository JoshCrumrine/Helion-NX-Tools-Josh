# NX 2506
# Author:  jo388c
# Created: 2026-10-29
# Copies the part name (Teamcenter item name, the DB_PART_NAME attribute) of the selected components
# to the Windows clipboard.
#
# Once installed with Install-Copy-Part-Number.bat (see README.md), this runs when you right-click a
# component in the Assembly Navigator and choose "Copy Part Name", or choose Edit > Copy Part Name.
# It also works without installing anything: select components, then File -> Execute -> NX Open...
# and pick this file.
#
# Works like Copy Part Number, and copy_part_number.py (in this folder) does the work: one name per
# line, each part once, in selection order. For a component whose part is not loaded, the name comes
# from Teamcenter. The status line says what was copied. Nothing in the model changes.
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import copy_part_number  # noqa: E402


def main(args):
    copy_part_number.copy_selected(copy_part_number.NAME)


if __name__ == '__main__':
    main(sys.argv[1:])
