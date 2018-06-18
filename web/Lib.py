import datetime
import time
from spidev import SpiDev

from RPi import GPIO
from smbus import SMBus

import logging

logging.basicConfig(level=logging.DEBUG)
log = logging.getLogger("LIB_LOG")


class WaterPump:
    # triggered using an SSR
    def __init__(self, pin):
        GPIO.setup(pin, GPIO.OUT)
        GPIO.output(pin, 1)
        self.pin = pin

    def on(self):
        GPIO.output(self.pin, 0)

    def off(self):
        GPIO.output(self.pin, 1)

    def pump_amount(self, ml):
        # flow rate: 800cc/min
        # ==> 13.33 ml/s
        # 1000/13.33 ==> 75ms/ml
        # THEORETICAL --> LOSS THROUGH OVERFLOW
        sec = (ml * 220) / 1000  # 220 SEEMS ABOUT RIGHT AFTER TESTING
        self.on()
        time.sleep(sec)
        self.off()


class Boiler:
    def __init__(self, pin):
        GPIO.setup(pin, GPIO.OUT)
        self.pin = pin  # PIN TO SWITCH THE RELAY
        self.off()

    def on(self):
        GPIO.output(self.pin, 1)

    def off(self):
        GPIO.output(self.pin, 0)


class MCP3008:
    def __init__(self, bus=0, device=0):
        self.bus = bus
        self.device = device
        self.spi = SpiDev()

    def read_channel(self, ch):
        self.spi.open(self.bus, self.device)
        self.spi.max_speed_hz = int(10e5)
        commando_bytes = [1, (8 | ch) << 4, 0]
        val = self.spi.xfer2(commando_bytes)
        self.spi.close()
        # print("MCP MSB: {}".format(bin(val[1])))
        # print("MCP LSB: {}".format(bin(val[2])))
        val = ((val[1] & 3) << 8) | val[2]
        # print("MCP VALUE: {}".format(bin(val)))
        return val


class NTC:
    def __init__(self, adc: MCP3008, channel: int):
        self.adc = adc
        self.channel = channel

    def get_value(self):
        return self.adc.read_channel(self.channel)

    # def check_temp(self, temp, hyst):
    #     # negative is too low, positive too high, 0 is good
    #     curr_temp = self.get_temp()
    #     hyst_val = hyst / 2
    #     if curr_temp < (temp - hyst_val):
    #         return -1
    #     if curr_temp > (temp + hyst_val):
    #         return 1
    #     return 0


class LDR:
    def __init__(self, adc: MCP3008, channel: int):
        self.adc = adc
        self.channel = channel

    def get_value(self):
        return self.adc.read_channel(self.channel)


class DS3121:
    def __init__(self, address, sqw_pin, channel=1, cb_on_alarm=print):
        """

        :param address: the i2c address of the device (usually 0x68)
        :param sqw_pin: the pin set high when alarm goes off
        :param channel:
        :param cb_on_alarm: callback function when an alarm goes off (default print)
        """
        self.i2c = SMBus(channel)
        self.address = address
        self.REG = {
            "SECONDS": 0x00,
            "MINUTES": 0x01,
            "HOUR": 0x02,
            "DAY": 0x03,
            "DATE": 0x04,
            "MONTH": 0x05,
            "YEAR": 0x06,

            "A1_SECONDS": 0x07,
            "A1_MINUTES": 0x08,
            "A1_HOUR": 0x09,
            "A1_DAY_DATE": 0x0A,

            "A2_MINUTES": 0x0B,
            "A2_HOUR": 0x0C,
            "A2_DAY_DATE": 0x0D,

            "CONTROL": 0x0E,
            "CONTROL_STATUS": 0x0F,
            "AGING_OFFSET": 0x10,
            "MSB_TEMP": 0x11,
            "LSB_TEMP": 0x12
        }
        self.sqw = sqw_pin
        # RESET ALARM
        self.reset()
        # ENABLE SQW FOR ALARM 1
        self.i2c.write_byte_data(self.address, self.REG["CONTROL"], 5)
        # PIN SETUP
        GPIO.setup(sqw_pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

    def reset(self):
        self.i2c.write_byte_data(self.address, self.REG["CONTROL_STATUS"], 0)
        self.i2c.write_byte_data(self.address, self.REG["A1_SECONDS"], 0)
        self.i2c.write_byte_data(self.address, self.REG["A1_MINUTES"], 0)
        self.i2c.write_byte_data(self.address, self.REG["A1_HOUR"], 0)

    def set_datetime(self, value: datetime.datetime):
        self.i2c.write_byte_data(self.address, self.REG["SECONDS"], self.int2bcd(value.second))
        self.i2c.write_byte_data(self.address, self.REG["MINUTES"], self.int2bcd(value.minute))
        self.i2c.write_byte_data(self.address, self.REG["HOUR"], self.int2bcd(value.hour))
        self.i2c.write_byte_data(self.address, self.REG["DATE"], self.int2bcd(value.day))
        self.i2c.write_byte_data(self.address, self.REG["MONTH"], self.int2bcd(value.month))
        self.i2c.write_byte_data(self.address, self.REG["YEAR"], self.int2bcd(value.year))
        self.i2c.write_byte_data(self.address, self.REG["DAY"], value.isoweekday())

    def get_datetime(self):
        sc = self.bcd2int(self.i2c.read_byte_data(self.address, self.REG["SECONDS"]))
        mn = self.bcd2int(self.i2c.read_byte_data(self.address, self.REG["MINUTES"]))
        hr = self.bcd2int(self.i2c.read_byte_data(self.address, self.REG["HOUR"]))
        dte = self.bcd2int(self.i2c.read_byte_data(self.address, self.REG["DATE"]))
        mth = self.bcd2int(self.i2c.read_byte_data(self.address, self.REG["MONTH"]))
        yr = self.bcd2int(self.i2c.read_byte_data(self.address, self.REG["YEAR"]))
        day = self.bcd2int(self.i2c.read_byte_data(self.address, self.REG["DAY"]))
        log.debug("CURR DATETIME DAY OF WEEK: {}".format(day))
        return datetime.datetime(second=sc, minute=mn, hour=hr, day=dte, month=mth, year=yr)

    def set_alarm(self, day, hour, minute):
        # reset alarm pin
        self.reset()

        self.i2c.write_byte_data(self.address, self.REG["A1_MINUTES"], self.int2bcd(minute))
        self.i2c.write_byte_data(self.address, self.REG["A1_HOUR"], self.int2bcd(hour))
        self.i2c.write_byte_data(self.address, self.REG["A1_DAY_DATE"], self.int2bcd(day))
        self.log_alarm()

    def log_alarm(self):
        mn = self.bcd2int(self.i2c.read_byte_data(self.address, self.REG["A1_MINUTES"]))
        hr = self.bcd2int(self.i2c.read_byte_data(self.address, self.REG["A1_HOUR"]))
        dy = self.bcd2int(self.i2c.read_byte_data(self.address, self.REG["A1_DAY_DATE"]))
        sc = self.bcd2int(self.i2c.read_byte_data(self.address, self.REG["A1_SECONDS"]))
        log.info("ALARM: {}:{}:{} DY({})".format(hr, mn, sc, dy))

    def clear_alarm(self):
        self.reset()

    @staticmethod
    def bcd2int(value):
        return ((value >> 4) * 10) + (value & 0x0F)

    @staticmethod
    def int2bcd(value):
        return ((value // 10) << 4) | (value % 10)


class Dispenser:
    def __init__(self, pin):
        """

        :param pin: The pin used to control the motor
        """
        self.pin = pin
        GPIO.setup(pin, GPIO.OUT)
        self.pwm = GPIO.PWM(self.pin, 50)
        self.pwm.start(0)

    def scoop(self):
        for i in range(2):
            self.pwm.ChangeDutyCycle(10)
            time.sleep(1)
            self.pwm.ChangeDutyCycle(5)
            time.sleep(1)
            self.pwm.ChangeDutyCycle(7.5)
            time.sleep(.1)
            self.pwm.ChangeDutyCycle(0)

    @staticmethod
    def angle_to_value(value):
        return 1 + ((value + 90) / 180)


class Reed:
    def __init__(self, pin: int, nc: bool = False):
        """
        :param pin: The GPIO pin where the data signal is read
        :param nc: Normally closed (1 is closed, 0 is open)
        """
        GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        self.pin = pin
        self.nc = nc

    def check_value(self):
        value = GPIO.input(self.pin)
        if self.nc:
            return value
        return not value
