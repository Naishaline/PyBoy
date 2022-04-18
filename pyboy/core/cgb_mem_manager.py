from . import mem_manager


class CgbMemoryManager(mem_manager.MemoryManager):
    def __init__(self, mb, bootrom, cartridge, lcd, timer, sound, ram, renderer):
        super().__init__(mb, bootrom, cartridge, lcd, timer, sound, ram, renderer)

        self.hdma1 = 0
        self.hdma2 = 0
        self.hdma3 = 0
        self.hdma4 = 0
        self.hdma5 = 0xFF

        self.transfer_active = False
        self.curr_src = 0
        self.curr_dst = 0

        self.key1 = 0
        self.is_double_speed = False

    def get_io(self, addr):
        #print("%3s %6s" % ("get", hex(addr)))
        if addr == 0xFF04:
            return self.timer.DIV
        elif addr == 0xFF05:
            return self.timer.TIMA
        elif addr == 0xFF06:
            return self.timer.TMA
        elif addr == 0xFF07:
            return self.timer.TAC
        elif 0xFF10 <= addr < 0xFF40:
            if self.mb.sound_enabled:
                return self.sound.get(addr - 0xFF10)
            else:
                return 0
        elif addr == 0xFF40:
            return self.lcd.LCDC.value
        elif addr == 0xFF42:
            return self.lcd.SCY
        elif addr == 0xFF43:
            return self.lcd.SCX
        elif addr == 0xFF47:
            return self.lcd.BGP.value
        elif addr == 0xFF48:
            return self.lcd.OBP0.value
        elif addr == 0xFF49:
            return self.lcd.OBP1.value
        elif addr == 0xFF4A:
            return self.lcd.WY
        elif addr == 0xFF4B:
            return self.lcd.WX
        # CGB registers
        elif addr == 0xFF4D:
            return self.get_key1()
        elif addr == 0xFF4F:
            return self.lcd.vbk.get()
        elif addr == 0xFF68:
            return self.lcd.bcps.get() | 0x40
        elif addr == 0xFF69:
            return self.lcd.bcpd.get()
        elif addr == 0xFF6A:
            return self.lcd.ocps.get() | 0x40
        elif addr == 0xFF6B:
            return self.lcd.ocpd.get()
        elif addr == 0xFF70:
            return self.ram.read(addr)
        elif 0xFF51 <= addr <= 0xFF55:
            return self.get_hdma(addr)
        else:
            return self.ram.read(addr)

    def set_io(self, addr, value):
        #print("%3s %6s %3s" % ("set", hex(addr), hex(value)))
        if addr == 0xFF00:
            self.ram.write(addr, self.mb.interaction.pull(value))
        elif addr == 0xFF01:
            self.mb.serialbuffer += chr(value)
            self.ram.write(addr, value)
        elif addr == 0xFF04:
            self.timer.DIV = 0
        elif addr == 0xFF05:
            self.timer.TIMA = value
        elif addr == 0xFF06:
            self.timer.TMA = value
        elif addr == 0xFF07:
            self.timer.TAC = value & 0b111
        elif 0xFF10 <= addr < 0xFF40:
            if self.mb.sound_enabled:
                self.sound.set(addr - 0xFF10, value)
        elif addr == 0xFF40:
            self.lcd.LCDC.set(value)
        elif addr == 0xFF42:
            self.lcd.SCY = value
        elif addr == 0xFF43:
            self.lcd.SCX = value
        elif addr == 0xFF46:
            self.transfer_DMA(value)
        elif addr == 0xFF47:
            if self.mb.cartridge.is_cgb:
                self.lcd.BGP.set(value)
            else:
                self.renderer.clearcache |= self.lcd.BGP.set(value)
        elif addr == 0xFF48:
            if self.mb.cartridge.is_cgb:
                self.lcd.OBP0.set(value)
            else:
                self.renderer.clearcache |= self.lcd.OBP0.set(value)
        elif addr == 0xFF49:
            if self.mb.cartridge.is_cgb:
                self.lcd.OBP1.set(value)
            else:
                self.renderer.clearcache |= self.lcd.OBP1.set(value)

        elif addr == 0xFF4A:
            self.lcd.WY = value
        elif addr == 0xFF4B:
            self.lcd.WX = value
        elif addr == 0xFF50 and self.mb.bootrom_enabled and (value == 0x1 or value == 0x11):
            self.mb.bootrom_enabled = False
            self.ram.write(addr, value)
        # CGB registers
        elif addr == 0xFF4D:
            self.set_key1(value)
        elif addr == 0xFF4F:
            self.lcd.vbk.set(value)
        elif addr == 0xFF68:
            self.lcd.bcps.set(value)
        elif addr == 0xFF69:
            self.lcd.bcpd.set(value)
            self.renderer.clearcache = True
        elif addr == 0xFF6A:
            self.lcd.ocps.set(value)
        elif addr == 0xFF6B:
            self.lcd.ocpd.set(value)
            self.renderer.clearcache = True
        elif addr == 0xFF70:
            self.ram.write(addr, value)
        elif 0xFF51 <= addr <= 0xFF54:
            self.set_hdma(addr, value)
        elif addr == 0xFF55:
            self.set_hdma5(value)
        else:
            self.ram.write(addr, value)

    def set_key1(self, value):
        self.key1 = value & 0xFF

    def get_key1(self):
        return self.key1

    def switch_speed(self):
        bit0 = self.key1 & 0b1
        if bit0 == 1:
            self.is_double_speed = not self.is_double_speed
            self.key1 ^= 0b10000001

    def set_hdma5(self, value):
        if self.transfer_active:
            bit7 = value & 0x80
            if bit7 == 0:
                # terminate active transfer
                self.transfer_active = False
                self.hdma5 = (self.hdma5 & 0x7F) | 0x80
            else:
                self.hdma5 = value & 0x7F
        else:
            self.hdma5 = value & 0xFF
            bytes_to_transfer = ((value & 0x7F) * 16) + 16
            src = (self.hdma1 << 8) | (self.hdma2 & 0xF0)
            dst = ((self.hdma3 & 0x1F) << 8) | (self.hdma4 & 0xF0)
            dst |= 0x8000

            transfer_type = value >> 7
            if transfer_type == 0:
                # General purpose DMA transfer
                for i in range(bytes_to_transfer):
                    self.setitem(dst + i, self.getitem(src + i))
                self.hdma5 = 0xFF
                self.hdma4 = 0xFF
                self.hdma3 = 0xFF
                self.hdma2 = 0xFF
                self.hdma1 = 0xFF
            else:
                # Hblank DMA transfer
                # set 0th bit to 0
                self.hdma5 = self.hdma5 & 0x7F
                self.transfer_active = True
                self.curr_dst = dst
                self.curr_src = src

    def do_potential_transfer(self):
        if self.transfer_active:

            src = self.curr_src & 0xFFF0
            dst = (self.curr_dst & 0x1FF0) | 0x8000

            for i in range(0x10):
                self.setitem(dst + i, self.getitem(src + i))

            self.curr_dst += 0x10
            self.curr_src += 0x10

            if self.curr_dst == 0xA000:
                self.curr_dst = 0x8000

            if self.curr_src == 0x8000:
                self.curr_src = 0xA000

            self.hdma1 = self.curr_src & 0xFF00
            self.hdma2 = self.curr_src & 0x00FF

            self.hdma3 = self.curr_dst & 0xFF00
            self.hdma4 = self.curr_dst & 0x00FF

            self.hdma5 -= 1
            if self.hdma5 == -1:
                self.transfer_active = False
                self.hdma5 = 0xFF

    def get_hdma(self, reg):
        if 0xFF51 <= reg <= 0xFF54:
            raise Exception("Can not read HDMA1-HDMA4")
        else:
            #print("hdma5 read : %s" % hex(self.hdma5))
            return self.hdma5 & 0xFF

    def set_hdma(self, reg, value):
        if reg == 0xFF51:
            self.hdma1 = value
        elif reg == 0xFF52:
            self.hdma2 = value
        elif reg == 0xFF53:
            self.hdma3 = value
        elif reg == 0xFF54:
            self.hdma4 = value
