# I2CExt.py

from machine import Pin, I2C

def install(vm):
    # store multiple I2C buses by index
    vm.i2c_buses = {}

    def do_i2c_init(vmm):
        freq  = vmm.pop()
        sda   = vmm.pop()
        scl   = vmm.pop()
        iface = vmm.pop()
        vmm.i2c_buses[iface] = I2C(iface, scl=Pin(scl), sda=Pin(sda), freq=freq)

    def do_i2c_read(vmm):
        bus   = vmm.pop()   # which bus to use
        addr  = vmm.pop()
        reg   = vmm.pop()
        data = bytearray(1)
        vmm.i2c_buses[bus].readfrom_mem_into(addr, reg, data)
        vmm.push(data[0])

    def do_i2c_write(vmm):
        bus   = vmm.pop()   # which bus to use
        addr  = vmm.pop()
        reg   = vmm.pop()
        val   = vmm.pop()
        vmm.i2c_buses[bus].writeto_mem(addr, reg, bytes([val]))

    def do_i2c_string(vmm):
        """I2C" ...": send a string literal to an I2C device (interpret or compile)."""
        raw = vmm._next_line()
        if raw is None or '"' not in raw:
            raise RuntimeError('Unterminated string for I2C"')
        string, _ = raw.split('"', 1)

        if vmm.compiling:
            def _i2c_send(vm2, s=string):
                bus  = vm2.pop()
                addr = vm2.pop()
                vm2.i2c_buses[bus].writeto(addr, s.encode())
            vmm._emit_op(_i2c_send)
        else:
            bus  = vmm.pop()
            addr = vmm.pop()
            vmm.i2c_buses[bus].writeto(addr, string.encode())

    vmm = vm
    vmm.add_fn("/I2C", do_i2c_init)
    vmm.add_fn("I2C@", do_i2c_read)
    vmm.add_fn("I2C!", do_i2c_write)
    vmm.add_fn('I2C"', do_i2c_string, immediate=True)

