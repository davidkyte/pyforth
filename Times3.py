# Forth extensions

from forth_vm import ForthVM

def install(vm):

    # multiply top of stack by 3
    def times3(vm):
        n = vm.pop()
        vm.push(n * 3)

    vm.add_fn("3*", times3)



