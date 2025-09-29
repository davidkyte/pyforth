# Forth extensions

from forth_vm import ForthVM


def abc(vm):

    vm.interpret( ' : abc ." abc ..." cr ;' )

def install(vm):
    # multiply top of stack by 5
    def times5(vm):
        n = vm.pop()
        vm.push(n * 5)

    vm.add_fn("5*", times5)
    abc( vm )

