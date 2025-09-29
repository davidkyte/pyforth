#!/usr/bin/python3

# pf_main.py
# Runner for the Forth VM. Keeps MicroPython-friendly imports.

from forth_vm import ForthVM

import os

from Extn import install_extn


def main():
    print("PyForth")
    vm = ForthVM()

    install_extn(vm)

    # Auto-load 0.txt if present (silently)
    try:
        if "0.txt" in os.listdir():
            vm.interpret( '0 load' )
    except Exception:
        pass

    vm.repl()

if __name__ == "__main__":
    main()

