#!/usr/bin/env python3
"""
This is a NodeServer for Rachio irrigation controllers originaly by fahrer16 (Brian Feeney)
and now developed by JimBo.Automates
Based on template for Polyglot v2 written in Python2/3 by Einstein.42 (James Milne) milne.james@gmail.com
"""

from udi_interface import Interface
from nodes import VERSION,Controller

if __name__ == "__main__":
    try:
        polyglot = Interface([])
        polyglot.start(VERSION)
        polyglot.updateProfile()
        polyglot.setCustomParamsDoc()
        control = Controller(polyglot, 'controller', 'controller', 'Ranchio')
        polyglot.runForever()
    except (KeyboardInterrupt, SystemExit):
        sys.exit(0)

