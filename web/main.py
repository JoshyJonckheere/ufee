from RPi import GPIO

import datetime
import logging
import subprocess
from Lib import *
from pathlib import Path
import mysql.connector as mariadb

logging.basicConfig(level=logging.DEBUG)
log = logging.getLogger("MAIN_LOG")


class Device:
    def __init__(self):
        GPIO.cleanup()
        # pinmode BCM
        GPIO.setmode(GPIO.BCM)
        # set class parameters
        self.adc = MCP3008()
        self.water_sensor = Reed(12)
        self.coffee_check = LDR(self.adc, 0)
        self.cup_check = LDR(self.adc, 1)
        self.temp_sensor = NTC(self.adc, 2)
        self.boiler = Boiler(25)
        self.pump = WaterPump(20)
        self.dispenser = Dispenser(16)

        self.songpath = None
        self.player = None

        self.alarm_coffee = 0
        self.alarm_water = 0
        self.cup_val = 750  # TEST TO GET RIGHT VALUE

        # self.rtc = DS3121(0x68, 17, cb_on_alarm=self.play_alarm())
        self.rtc = DS3121(0x68, 17)
        self.rtc.set_datetime(datetime.datetime.now())
        log.info(self.rtc.get_datetime())
        # ADDING EDGE DETECTION
        log.debug("SQW VAL: {}".format(GPIO.input(self.rtc.sqw)))
        GPIO.add_event_detect(self.rtc.sqw, GPIO.FALLING, callback=self.play_alarm)

        self.update_alarm()

    def machine_ready(self):
        if not self.water_sensor.check_value():
            return [False, "Refill water"]
        log.debug("COFFEE CHECK VALUE: {}".format(self.coffee_check.get_value()))
        if self.coffee_check.get_value() < 950:  # TEST TO CALIBRATE
            return [False, "Refill coffee"]
        log.debug("CUP SENSOR VALUE: {}".format(self.cup_check.get_value()))
        if self.cup_check.get_value() < self.cup_val:  # TEST TO CALIBRATE
            return [False, "Place cup"]

        return [True, "The machine is ready to use"]

    def brew(self, coffee, water):
        if self.machine_ready()[0]:  # ADD [0] TO ENABLE!!
            if isinstance(coffee, int) and coffee > 0 and isinstance(water, int) and water > 0:
                log.info("HEATING...")
                self.boiler.on()
                print("TEMP SENSOR VALUE: {}".format(self.temp_sensor.get_value()))
                while self.temp_sensor.get_value() > 200:
                    log.info("TEMP SENSOR VALUE: {}".format(self.temp_sensor.get_value))
                self.boiler.off()
                log.info("ADDING {} SCOOPS OF COFFEE...".format(coffee))
                for i in range(coffee):
                    log.info("SCOOP {}".format(i))
                    self.dispenser.scoop()
                log.info("POORING {}ML OF WATER...".format(water))
                self.pump.pump_amount(water)
                log.info("ENJOY!")
                return True
            return False

    def update_alarm(self):
        log.debug("UPDATING ALARM!")
        a = get_next_alarm()
        if a:
            # GET DATA
            alarm = get_alarm(a[0])
            coffee = get_coffee(alarm[0][5])
            song = get_song(alarm[0][4])

            # SET ALARM
            log.debug("ALARM UPDATED")
            self.rtc.reset()
            self.rtc.set_alarm(alarm[0][3], alarm[0][1], alarm[0][2])

            # SET ALARM PARAMETERS
            self.alarm_water = coffee[0][1]
            self.alarm_coffee = coffee[0][2]
            self.set_song(song[0][2])

            # LOGGING VALUES
            log.debug("NEXT ALARM: {}".format(a))
            log.debug("ALARM: {}".format(alarm))
            log.debug("ALARM SONG: {}".format(song))
            log.debug("ALARM COFFEE: {}".format(coffee))
        else:
            log.debug("NO ALARM ANYTIME SOON")
            self.rtc.clear_alarm()
        log.debug(self.rtc.get_datetime())
        self.rtc.log_alarm()

    def set_song(self, song_title):
        self.songpath = Path("web/static/songs/", song_title)

    def play_song(self):
        self.player = subprocess.Popen(["omxplayer", str(self.songpath)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE)

    def stop_song(self):
        if self.player is not None:
            self.player.stdin.write(b"q")

    def play_alarm(self):
        log.debug("CALLED PLAY_ALARM()")
        if self.alarm_coffee != 0:
            log.debug("PLAYING ALARM")
            self.play_song()
            self.brew(self.alarm_coffee, self.alarm_water)
            while self.cup_check.get_value() > self.cup_val:
                continue
            self.stop_song()
            self.update_alarm()
        else:
            log.debug("CALLBACK INITIALISATION")


def get_data(sql, params=None):
    conn = mariadb.connect(database='project1', user='project1-sensor', password='sensorpassword')
    cursor = conn.cursor()
    records = []
    try:
        log.info(sql)
        cursor.execute(sql, params)
        result = cursor.fetchall()
        for row in result:
            records.append(list(row))

    except Exception as e:
        log.error("Error on fetching data: {0})".format(e))

    cursor.close()
    conn.close()

    return records


def get_next_alarm():
    today = datetime.datetime.today().weekday() + 1
    if today == 7:
        tomorrow = 1
    else:
        tomorrow = today + 1
    curr_hour = datetime.datetime.now().hour
    curr_min = datetime.datetime.now().minute
    next_alarm = False
    log.debug("NEXT ALARM: TODAY = {} AND TOMORROW = {}".format(today, tomorrow))

    next_alarms = get_data("select A.alarmID, A.hour, A.minutes, D.dayID from alarms as A "
                           "join alarmDays as D "
                           "on A.alarmID = D.alarmID "
                           "where (D.dayID = %s "
                           "or D.dayID = %s) "
                           "and A.active = 1 "
                           "order by D.dayID ASC, "
                           "A.hour ASC, "
                           "A.minutes ASC,"
                           "A.alarmID ASC",
                           [today, tomorrow, ])

    for a in next_alarms:
        log.debug("NEXT ALARM LOOP: {}-{}-{}".format(a[3], a[1], a[2]))
        if a[3] == today:
            if a[1] > curr_hour or (a[1] == curr_hour and a[2] > curr_min):
                next_alarm = a
                break
            continue
        next_alarm = a
        break
    log.debug("FETCH NEXT ALARM: {}".format(next_alarm))
    return next_alarm


def get_alarm(alarm_id):
    return get_data("select alarmID, hour, minutes, active, songID, coffeeID, username "
                    "from alarms "
                    "where alarmID = %s",
                    [alarm_id, ])


def get_song(song_id):
    return get_data("select title, artist, filename, public, username "
                    "from songs "
                    "where songID = %s",
                    [song_id, ])


def get_coffee(coffee_id):
    return get_data("select name, "
                    "amt_water, "
                    "amt_coffee, "
                    "username, "
                    "public "
                    "from coffees "
                    "where coffeeID = %s;",
                    [coffee_id, ])


def main():
    # ONLY FOR TESTING PURPOSES
    GPIO.setmode(GPIO.BCM)
    adc = MCP3008()
    water_sensor = Reed(12)
    coffee_check = LDR(adc, 0)
    cup_check = LDR(adc, 1)
    temp_sensor = NTC(adc, 2)
    boiler = Boiler(25)
    pump = WaterPump(20)
    dispenser = Dispenser(16)
    try:
        while 1:
            dispenser.scoop()
            time.sleep(5)
    except KeyboardInterrupt:
        boiler.off()
        pump.off()
    finally:
        GPIO.cleanup()


if __name__ == '__main__':
    main()
