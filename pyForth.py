
"""
file     pyForth
time     2025-09-18
author   Dr David Kyte
email   david.kyte@gmail.com
license  MIT License
"""

import forth_vm
from forth_vm import ForthVM
import os
from Extn import install_extn

vm=none


"""
import forth_vm
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
"""

class pyForth:
    """
    note:
        en: ''
    details:
        color: '#0fb1d2'
        link: ''
        image: ''
        category: Custom
    example: ''
    """

    def __init__(self):
        """
        label:
            en: '%1 init'
        """
        global vm
        
        print("PyForth")
        vm = ForthVM()

        install_extn(vm)
        
        pass

    def run(self):
        """
        label:
            en: method %1
        """

        global vm
        
        # Auto-load 0.txt if present (silently)
        try:
            if "0.txt" in os.listdir():
                vm.interpret( '0 load' )
        except Exception:
            pass
                    
        vm.repl()

        pass


