# SPIExt.py

from machine import Pin, SPI

def install(vm):
    # store multiple SPI buses by index
    vm.spi_buses = {}

    def do_spi_init(vmm):
        baud   = vmm.pop()
        miso   = vmm.pop()
        mosi   = vmm.pop()
        sck    = vmm.pop()
        iface  = vmm.pop()
        vmm.spi_buses[iface] = SPI(iface,
            baudrate=baud,
            polarity=0,
            phase=0,
            bits=8,
            firstbit=SPI.MSB,
            sck=Pin(sck),
            mosi=Pin(mosi),
            miso=Pin(miso))

    def do_spi_read(vmm):
        bus    = vmm.pop()
        nbytes = vmm.pop()
        buf = vmm.spi_buses[bus].read(nbytes)
        for b in buf[::-1]:   # push in reverse so stack order is b0 ... b[n-1]
            vmm.push(b)

    def do_spi_write(vmm):
        bus    = vmm.pop()
        nbytes = vmm.pop()
        data = []
        for _ in range(nbytes):
            data.insert(0, vmm.pop())  # reversed collection
        vmm.spi_buses[bus].write(bytes(data))

    def do_spi_string(vmm):
        """SPI" ...": send a string literal over SPI (interpret or compile)."""
        # Get the rest of the current line from the input buffer
        raw = vmm._next_line()
        if raw is None or '"' not in raw:
            raise RuntimeError('Unterminated string for SPI"')
        string, _ = raw.split('"', 1)

        if vmm.compiling:
            # Compile-time: emit a runtime action
            def _spi_send(vm2, s=string):
                bus = vm2.pop()
                vm2.spi_buses[bus].write(s.encode())
            vmm._emit_op(_spi_send)
        else:
            # Interpret-time: send immediately
            bus = vmm.pop()
            vmm.spi_buses[bus].write(string.encode())

    vmm = vm
    vmm.add_fn("/SPI", do_spi_init)
    vmm.add_fn("SPI@", do_spi_read)
    vmm.add_fn("SPI!", do_spi_write)
    vmm.add_fn('SPI"', do_spi_string, immediate=True)

