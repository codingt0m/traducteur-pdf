#!/usr/bin/env python3
"""Ligne de commande : python traduire_pdf.py --help"""

import sys

from pdf_traducteur.cli import main

if __name__ == "__main__":
    sys.exit(main())
