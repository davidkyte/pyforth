# pin_ext.py
# Forth extension for GPIO pin manipulation

from machine import Pin # Corrected import statement

from forth_vm import ForthVM
# A dictionary to hold our pin objects
pin_objects = {}

# Forth word: <mode> <pin_number> /PIN
def prim_pin(vm):
    """( mode n -- ) Sets pin n to the specified mode."""
    pin_num = vm.pop()
    mode = vm.pop()
    
    # We map the Forth constants (0, 1) to the Pin class constants
    pin_mode = None
    if mode == 0:
        pin_mode = Pin.IN
    elif mode == 1:
        pin_mode = Pin.OUT
    else:
        raise RuntimeError("Invalid pin mode. Use IN or OUT.")

    try:
        if pin_num not in pin_objects:
            pin_objects[pin_num] = Pin(pin_num, mode=pin_mode)
        else:
            pin_objects[pin_num].init(mode=pin_mode)
    except Exception as e:
        raise RuntimeError(f"Pin {pin_num} initialization failed: {e}")

# Forth word: <state> <pin_number> PIN!
def prim_pin_set_state(vm):
    """( state n -- ) Sets the state of pin n."""
    pin_num = vm.pop()
    state = vm.pop()
    if pin_num not in pin_objects:
        raise RuntimeError(f"Pin {pin_num} not initialized. Use IN /PIN or OUT /PIN first.")
    
    pin = pin_objects[pin_num]
    try:
        if state == 0:
            pin.off()
        elif state == 1:
            pin.on()
        else:
            raise RuntimeError("Invalid state. Use 0 for off, 1 for on.")
    except Exception as e:
        raise RuntimeError(f"Failed to set state for pin {pin_num}: {e}")

# Forth word: <pin_number> PIN@
def prim_pin_get_state(vm):
    """( n -- state ) Reads the state of pin n."""
    pin_num = vm.pop()
    if pin_num not in pin_objects:
        raise RuntimeError(f"Pin {pin_num} not initialized. Use IN /PIN or OUT /PIN first.")
    
    pin = pin_objects[pin_num]
    try:
        state = pin.value()
        vm.push(state)
    except Exception as e:
        raise RuntimeError(f"Failed to read state for pin {pin_num}: {e}")

def install_pin_ext(vm: ForthVM):
    """Installs the pin extension words into the Forth VM."""
    vm.add_fn("/PIN", prim_pin)
    vm.add_fn("PIN!", prim_pin_set_state)
    vm.add_fn("PIN@", prim_pin_get_state)
    print("Pin extension loaded.")
