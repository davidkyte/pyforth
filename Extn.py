# Forth extensions

from forth_vm import ForthVM
import sys

# ==================== Primitives ====================

def dox10(vm):
    n = vm.pop()
    vm.push(n * 10)

def do_lshift(vm):
    u = vm.pop(); x = vm.pop()
    vm.push(x << u)

def do_rshift(vm):
    u = vm.pop(); x = vm.pop()
    vm.push(x >> u)

def do_and(vm):
    a = vm.pop(); b = vm.pop()
    vm.push(b & a)

def do_or(vm):
    a = vm.pop(); b = vm.pop()
    vm.push(b | a)

def do_xor(vm):
    a = vm.pop(); b = vm.pop()
    vm.push(b ^ a)

def do_invert(vm):
    x = vm.pop()
    vm.push(~x)

def do_ashift(vm):
    u = vm.pop(); x = vm.pop()
    vm.push(x >> u)  # arithmetic shift

def do_python(vm):
    """Load and execute a Python file with access to the current VM.
       If the file defines install(vm), it will be called automatically."""
    fname = vm._next_token()
    if not fname:
        raise RuntimeError("PYTHON requires a filename")
    try:
        with open(fname, "r") as f:
            code = f.read()
            ns = {"vm": vm}
            exec(code, ns)
            if "install" in ns and callable(ns["install"]):
                ns["install"](vm)
    except Exception as e:
        raise RuntimeError(f"PYTHON error loading {fname}: {e}")

# ==================== Inline Python <P ... P> ====================

def do_p_start(vm):
    """Enter Python capture mode until a line with just P>."""
    vm._py_lines = []

def do_p_end(vm):
    """Execute the captured Python code (interpret or compile)."""
    if not hasattr(vm, "_py_lines"):
        raise RuntimeError("P> without <P")
    code = "\n".join(vm._py_lines)
    del vm._py_lines
    if vm.compiling:
        # Compile-time: emit runtime exec of this code
        def _run_python(vmm, src=code):
            exec(src, {"vm": vmm})
        vm._emit_op(_run_python)
    else:
        # Interpret-time: run immediately
        exec(code, {"vm": vm})

# Patch interpret AFTER ForthVM is imported
_old_interpret = ForthVM.interpret
def _interpret_with_py(self, line):
    if hasattr(self, "_py_lines"):
        if line.strip().upper() == "P>":
            do_p_end(self)
        else:
            self._py_lines.append(line.rstrip("\n"))
        return
    return _old_interpret(self, line)

ForthVM.interpret = _interpret_with_py

# ==================== Install ====================

def install_extn(vm):
    vm.add_fn("10*", dox10)

    # Shifts
    vm.add_fn("LSHIFT", do_lshift)
    vm.add_fn("RSHIFT", do_rshift)
    vm.add_fn("ASHIFT", do_ashift)

    # Bitwise ops
    vm.add_fn("AND", do_and)
    vm.add_fn("OR", do_or)
    vm.add_fn("XOR", do_xor)
    vm.add_fn("INVERT", do_invert)

    # Python loader
    vm.add_fn("PYTHON", do_python)

    # Inline Python
    vm.add_fn("<P", do_p_start, immediate=True)
    vm.add_fn("P>", do_p_end)

    # Example high-level word
    vm.interpret(': hi ." Hello ... " cr ;')

