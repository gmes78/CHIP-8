# -*- coding: utf-8 -*-
#
# Copyright © 2019 Joaquim Monteiro
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

from random import randint

from PySide2 import QtCore

from .display import VideoMemory
from .font import FONT_DATA
from .memory import Memory, FONT_START

PROGRAM_COUNTER_START = 512
STACK_POINTER_START = 82
TIMER_INTERVAL = 16


class UnimplementedInstruction(Exception):
    def __init__(self, instruction, address):
        self.instruction = instruction
        self.address = address

    def __str__(self):
        return f"Unimplemented instruction 0x{self.instruction:04X} at address 0x{self.address:03X}"


class Emulator(QtCore.QObject):
    display_changed = QtCore.Signal()
    emulation_error = QtCore.Signal(Exception)

    def __init__(self, rom, parent, debug=False):
        super().__init__(parent=parent)
        self.parent = parent
        self.debug = debug

        self.v = [0] * 16
        self.program_counter = PROGRAM_COUNTER_START
        self.index_register = 0
        self.stack_pointer = STACK_POINTER_START
        self.delay_timer = 0
        self.sound_timer = 0

        self.waiting_for_keypress = False
        self.keypress_target = None

        self.memory = Memory()
        self.video_memory = VideoMemory()
        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(TIMER_INTERVAL)
        self.timer.timeout.connect(self.decrement_timers)

        self.memory.load_font(FONT_DATA)
        self.memory.load_rom(rom)

        if self.debug:
            print("Memory:")
            print(self.memory)

    @QtCore.Slot()
    def decrement_timers(self):
        if self.delay_timer > 0:
            self.delay_timer -= 1

        if self.sound_timer > 0:
            self.sound_timer -= 1


    @QtCore.Slot()
    def run_once(self):
        if self.waiting_for_keypress:
            # Implementation of instruction 0xFX0A
            for key in range(16):
                if self.parent.is_key_pressed(key):
                    self.v[self.keypress_target] = key
                    self.waiting_for_keypress = False
                    break
            else:
                return

        instruction = int.from_bytes(self.memory[self.program_counter:self.program_counter+2], byteorder="big")
        self.program_counter += 2

        if instruction == 0x00E0:
            # Clear the screen
            if self.debug:
                print(f"[{instruction:04X}] Clearing the screen")
            self.video_memory.reset()
        elif instruction == 0x00EE:
            # Return from subroutine.
            self.stack_pointer -= 2
            self.program_counter = int.from_bytes(self.memory[self.stack_pointer:self.stack_pointer+2], byteorder="big")
            if self.debug:
                print(f"[{instruction:04X}] Returning from subroutine to address "
                      f"0x{self.program_counter:04X}")
        elif instruction & 0xF000 == 0x1000:
            # Jump to address.
            if self.debug:
                print(f"[{instruction:04X}] Jumping to address 0x{instruction & 0x0FFF:03X}")

            if self.program_counter - 2 == instruction & 0x0FFF:
                if self.debug:
                    print(f"[{instruction:04X}] Infinite jump detected, halting")
                self.parent.actionPause.setChecked(True)

            self.program_counter = instruction & 0x0FFF
        elif instruction & 0xF000 == 0x2000:
            # Call subroutine.
            if self.debug:
                print(f"[{instruction:04X}] Calling subroutine at address "
                      f"0x{instruction & 0x0FFF:03X}")
            return_address = int.to_bytes(self.program_counter, 2, byteorder="big")
            self.memory[self.stack_pointer:self.stack_pointer+2] = return_address

            self.stack_pointer += 2
            self.program_counter = instruction & 0x0FFF
        elif instruction & 0xF000 == 0x3000:
            # Skip the next instruction if the source register equals value.
            if self.debug:
                print(f"[{instruction:04X}] Conditional skip if register "
                      f"V{(instruction & 0x0F00) >> 8:X} equals 0x{instruction & 0x00FF:02X} "
                      f"({self.v[(instruction & 0x0F00) >> 8] == instruction & 0x00FF})")
            if self.v[(instruction & 0x0F00) >> 8] == instruction & 0x00FF:
                self.program_counter += 2
        elif instruction & 0xF000 == 0x4000:
            # Skip the next instruction if the source register does not equal value.
            if self.debug:
                print(f"[{instruction:04X}] Conditional skip if register "
                      f"V{(instruction & 0x0F00) >> 8:X} does not equal "
                      f"0x{instruction & 0x00FF:02X} "
                      f"({self.v[(instruction & 0x0F00) >> 8] != instruction & 0x00FF})")
            if self.v[(instruction & 0x0F00) >> 8] != instruction & 0x00FF:
                self.program_counter += 2
        elif instruction & 0xF00F == 0x5000:
            # Skip the next instruction if the registers have the same value.
            if self.debug:
                print(f"[{instruction:04X}] Conditional skip if the values of the registers "
                      f"V{(instruction & 0x0F00) >> 8:X} and V{(instruction & 0x00F0) >> 4:X} "
                      f"are equal ({self.v[(instruction & 0x0F00) >> 8] == self.v[(instruction & 0x00F0) >> 4]})")
            if self.v[(instruction & 0x0F00) >> 8] == self.v[(instruction & 0x00F0) >> 4]:
                self.program_counter += 2
        elif instruction & 0xF000 == 0x6000:
            # Move value to register
            if self.debug:
                print(f"[{instruction:04X}] Moving {instruction & 0x00FF:02X} to register "
                      f"V{(instruction & 0x0F00) >> 8:X}")
            self.v[(instruction & 0x0F00) >> 8] = instruction & 0x00FF
        elif instruction & 0xF000 == 0x7000:
            # Add value to register (wrapping addition, no carry)
            if self.debug:
                print(f"[{instruction:04X}] Adding {instruction & 0x00FF:02X} to register "
                      f"V{(instruction & 0x0F00) >> 8:X} (carry discarded)")
            self.v[(instruction & 0x0F00) >> 8] += instruction & 0x00FF
            while self.v[(instruction & 0x0F00) >> 8] > 255:
                self.v[(instruction & 0x0F00) >> 8] -= 256
        elif instruction & 0xF00F == 0x8000:
            # Sets the first register to the value of the second
            if self.debug:
                print(f"[{instruction:04X}] Setting register V{(instruction & 0x0F00) >> 8:X} to "
                      f"the value of register V{(instruction & 0x00F0) >> 4:X} "
                      f"(0x{self.v[(instruction & 0x00F0) >> 4]:02X})")
            self.v[(instruction & 0x0F00) >> 8] = self.v[(instruction & 0x00F0) >> 4]
        elif instruction & 0xF00F == 0x8001:
            # ORs the value of two registers, placing the result in the first
            if self.debug:
                print(f"[{instruction:04X}] ORing registers V{(instruction & 0x0F00) >> 8:X} and"
                      f" V{(instruction & 0x00F0) >> 4:X}")
            self.v[(instruction & 0x0F00) >> 8] = self.v[(instruction & 0x0F00) >> 8] | self.v[(instruction & 0x00F0) >> 4]
        elif instruction & 0xF00F == 0x8002:
            # ANDs the value of two registers, placing the result in the first
            if self.debug:
                print(f"[{instruction:04X}] ANDing registers V{(instruction & 0x0F00) >> 8:X} and"
                      f" V{(instruction & 0x00F0) >> 4:X}")
            self.v[(instruction & 0x0F00) >> 8] = self.v[(instruction & 0x0F00) >> 8] & self.v[(instruction & 0x00F0) >> 4]
        elif instruction & 0xF00F == 0x8003:
            # XORs the value of two registers, placing the result in the first
            if self.debug:
                print(f"[{instruction:04X}] XORing registers V{(instruction & 0x0F00) >> 8:X} and"
                      f" V{(instruction & 0x00F0) >> 4:X}")
            self.v[(instruction & 0x0F00) >> 8] = self.v[(instruction & 0x0F00) >> 8] ^ self.v[(instruction & 0x00F0) >> 4]
        elif instruction & 0xF00F == 0x8004:
            # Adds the value of the second register to the first
            if self.debug:
                print(f"[{instruction:04X}] Adding registers V{(instruction & 0x0F00) >> 8:X} and"
                      f" V{(instruction & 0x00F0) >> 4:X}")
            self.v[(instruction & 0x0F00) >> 8] += self.v[(instruction & 0x00F0) >> 4]
            carry = False
            while self.v[(instruction & 0x0F00) >> 8] > 255:
                self.v[(instruction & 0x0F00) >> 8] -= 256
                carry = True

            self.v[0xF] = 1 if carry else 0
        elif instruction & 0xF00F == 0x8005:
            # Subtracts the value of the second register from the first
            if self.debug:
                print(f"[{instruction:04X}] Subtracting registers "
                      f"V{(instruction & 0x0F00) >> 8:X} and V{(instruction & 0x00F0) >> 4:X}")
            self.v[(instruction & 0x0F00) >> 8] -= self.v[(instruction & 0x00F0) >> 4]
            borrow = False
            while self.v[(instruction & 0x0F00) >> 8] < 0:
                self.v[(instruction & 0x0F00) >> 8] += 256
                borrow = True

            self.v[0xF] = 0 if borrow else 1
        elif instruction & 0xF00F == 0x8006:
            # Shifts the value of the register to the right
            if self.debug:
                print(f"[{instruction:04X}] Shifting register V{(instruction & 0x0F00) >> 8:X} "
                      f"to the right")
            self.v[0xF] = self.v[(instruction & 0x0F00) >> 8] & 0b00000001
            self.v[(instruction & 0x0F00) >> 8] = self.v[(instruction & 0x0F00) >> 8] >> 1
        elif instruction & 0xF00F == 0x8007:
            # Sets the first register to the difference between second register and the first
            if self.debug:
                print(f"[{instruction:04X}] Subtracting registers "
                      f"V{(instruction & 0x00F0) >> 4:X} and V{(instruction & 0x0F00) >> 8:X}, "
                      f"placing the result in V{(instruction & 0x0F00) >> 8:X}")
            self.v[(instruction & 0x0F00) >> 8] = self.v[(instruction & 0x00F0) >> 4] - self.v[(instruction & 0x0F00) >> 8]
            borrow = False
            while self.v[(instruction & 0x0F00) >> 8] < 0:
                self.v[(instruction & 0x0F00) >> 8] += 256
                borrow = True

            self.v[0xF] = 0 if borrow else 1
        elif instruction & 0xF00F == 0x800E:
            # Shifts the value of the register to the left
            if self.debug:
                print(f"[{instruction:04X}] Shifting register V{(instruction & 0x0F00) >> 8:X} "
                      f"to the left")
            self.v[0xF] = (self.v[(instruction & 0x0F00) >> 8] & 0b10000000) >> 7
            self.v[(instruction & 0x0F00) >> 8] = self.v[(instruction & 0x0F00) >> 8] << 1
        elif instruction & 0xF00F == 0x9000:
            # Skip the next instruction if the registers have different values.
            if self.debug:
                print(f"[{instruction:04X}] Conditional skip if the values of the registers "
                      f"V{(instruction & 0x0F00) >> 8:X} and V{(instruction & 0x00F0) >> 4:X} "
                      f"differ ({self.v[(instruction & 0x0F00) >> 8] == self.v[(instruction & 0x00F0) >> 4]})")
            if self.v[(instruction & 0x0F00) >> 8] != self.v[(instruction & 0x00F0) >> 4]:
                self.program_counter += 2
        elif instruction & 0xF000 == 0xA000:
            # Move value to the index register.
            if self.debug:
                print(f"[{instruction:04X}] Moving 0x{instruction & 0x0FFF:03X} to the index "
                      f"register")
            self.index_register = instruction & 0x0FFF
        elif instruction & 0xF000 == 0xB000:
            # Jump to address plus the offset in register 0.
            if self.debug:
                print(f"[{instruction:04X}] Jumping to address "
                      f"0x{(instruction & 0x0FFF) + self.v[0]:03X} (0x{instruction & 0x0FFF:03X} +"
                      f" 0x{self.v[0]:02X} from register 0)")

            if self.program_counter - 2 == (instruction & 0x0FFF) + self.v[0]:
                if self.debug:
                    print(f"[{instruction:04X}] Infinite jump detected, halting")
                self.parent.actionPause.setChecked(True)

            self.program_counter = (instruction & 0x0FFF) + self.v[0]
        elif instruction & 0xF000 == 0xC000:
            # Move value to the index register.
            rand = randint(0, 255)
            if self.debug:
                print(f"[{instruction:04X}] Performing AND between a random number (0x{rand:02X})"
                      f" and the value 0x{instruction & 0x00FF:02X}, storing the result in "
                      f"register V{(instruction & 0x0F00) >> 8:X}")
            self.v[(instruction & 0x0F00) >> 8] = rand & (instruction & 0x00FF)
        elif instruction & 0xF000 == 0xD000:
            # Draw sprite.
            x = self.v[(instruction & 0x0F00) >> 8]
            y = self.v[(instruction & 0x00F0) >> 4]

            if self.debug:
                print(f"[{instruction:04X}] Drawing sprite from memory address "
                      f"0x{self.index_register:03X} ({instruction & 0x000F} tall) at coordinates"
                      f" {x}, {y}")

            sprite = self.memory[self.index_register:self.index_register + (instruction & 0x000F)]
            collision = self.video_memory.draw_sprite(x, y, sprite)

            if collision:
                if self.debug:
                    print(f"[{instruction:04X}] Sprite collision detected")
                self.v[0xF] = 1
            else:
                self.v[0xF] = 0

            self.display_changed.emit()
        elif instruction & 0xF0FF == 0xE09E:
            # Skip the next instruction if the key specified in the source register is pressed.
            if self.debug:
                print(f"[{instruction:04X}] Conditional skip if key from register "
                      f"V{(instruction & 0x0F00) >> 8:X} "
                      f"(0x{self.v[(instruction & 0x0F00) >> 8]:X}) is pressed")
            if self.parent.is_key_pressed(self.v[(instruction & 0x0F00) >> 8]):
                self.program_counter += 2
        elif instruction & 0xF0FF == 0xE0A1:
            # Skip the next instruction if the key specified in the source register is not pressed.
            if self.debug:
                print(f"[{instruction:04X}] Conditional skip if key from register "
                      f"V{(instruction & 0x0F00) >> 8:X} "
                      f"(0x{self.v[(instruction & 0x0F00) >> 8]}) is not pressed")
            if not self.parent.is_key_pressed(self.v[(instruction & 0x0F00) >> 8]):
                self.program_counter += 2
        elif instruction & 0xF0FF == 0xF007:
            # Read delay register
            if self.debug:
                print(f"[{instruction:04X}] Loading register V{(instruction & 0x0F00) >> 8:X} "
                      f"with the value of the delay timer (0x{self.delay_timer:X})")
            self.v[(instruction & 0x0F00) >> 8] = self.delay_timer
        elif instruction & 0xF0FF == 0xF00A:
            # Wait for key press and store it in the register
            if self.debug:
                print(f"[{instruction:04X}] Waiting for keypress to store in register"
                      f" V{(instruction & 0x0F00) >> 8:X}")
            self.keypress_target = (instruction & 0x0F00) >> 8
            self.waiting_for_keypress = True
        elif instruction & 0xF0FF == 0xF015:
            # Load delay register
            if self.debug:
                print(f"[{instruction:04X}] Loading the delay timer with value from register "
                      f"V{(instruction & 0x0F00) >> 8:X} "
                      f"(0x{self.v[(instruction & 0x0F00) >> 8]:X})")
            self.delay_timer = self.v[(instruction & 0x0F00) >> 8]
        elif instruction & 0xF0FF == 0xF018:
            # Load delay register
            if self.debug:
                print(f"[{instruction:04X}] Loading the sound timer with value from register "
                      f"V{(instruction & 0x0F00) >> 8:X} "
                      f"(0x{self.v[(instruction & 0x0F00) >> 8]:X})")
            self.sound_timer = self.v[(instruction & 0x0F00) >> 8]
        elif instruction & 0xF0FF == 0xF01E:
            # Adds the value in the register to the index register
            if self.debug:
                print(f"[{instruction:04X}] Adding the value from register "
                      f"V{(instruction & 0x0F00) >> 8:X} "
                      f"(0x{self.v[(instruction & 0x0F00) >> 8]:02X}) to the index register")
            self.index_register += self.v[(instruction & 0x0F00) >> 8]
            if self.index_register > 0xFFF:
                self.index_register -= 0x1000
                self.v[0xF] = 1
            else:
                self.v[0xF] = 0
        elif instruction & 0xF0FF == 0xF029:
            # Load index register with the location of the font for the value in the register
            if self.debug:
                print(f"[{instruction:04X}] Loading the index register with the address of the "
                      f"font for {self.v[(instruction & 0x0F00) >> 8]:X} from register"
                      f" V{(instruction & 0x0F00) >> 8:X}")
            self.index_register = FONT_START + self.v[(instruction & 0x0F00) >> 8] * 5
        elif instruction & 0xF0FF == 0xF033:
            # Store the binary coded decimal representation of the value
            # in the specified register in memory
            value = self.v[(instruction & 0x0F00) >> 8]

            if self.debug:
                print(f"[{instruction:04X}] Storing BCD representation of value {value} from "
                      f"register V{(instruction & 0x0F00) >> 8:X} in address"
                      f" 0x{self.index_register:03X}")

            self.memory[self.index_register] = value // 100
            value = value % 100
            self.memory[self.index_register + 1] = value // 10
            self.memory[self.index_register + 2] = value % 10
        elif instruction & 0xF0FF == 0xF055:
            # Store registers in memory
            if self.debug:
                print(f"[{instruction:04X}] Moving the first {((instruction & 0x0F00) >> 8) + 1} "
                      f"registers to memory address 0x{self.index_register:03X}")
            for i in range(((instruction & 0x0F00) >> 8) + 1):
                self.memory[self.index_register + i] = self.v[i]
        elif instruction & 0xF0FF == 0xF065:
            # Read registers from memory
            if self.debug:
                print(f"[{instruction:04X}] Moving value from memory address "
                      f"0x{self.index_register:03X} to the first"
                      f" {((instruction & 0x0F00) >> 8) + 1} registers")
            for i in range(((instruction & 0x0F00) >> 8) + 1):
                self.v[i] = self.memory[self.index_register + i]
        else:
            exception = UnimplementedInstruction(instruction, self.program_counter-2)
            self.emulation_error.emit(exception)
            raise exception
