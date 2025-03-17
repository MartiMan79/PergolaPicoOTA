# boot.py -- run on boot-up
import network, utime, machine, ntptime
from ota import OTAUpdater
from machine import Pin

LED = machine.Pin("LED",machine.Pin.OUT)
# Replace the following with your WIFI Credentials
SSID = "SmeetsHome"
SSID_PASSWORD = "mm837283"

LED(1)
firmware_url = "https://raw.githubusercontent.com/MartiMan79/PergolaPicoOTA/refs/heads/main/NoSensor/"

ota_updater = OTAUpdater(SSID, SSID_PASSWORD, firmware_url, "main.py")

ota_updater.download_and_install_update_if_available()

print("local time is:",(utime.localtime()))
ntptime.settime()
rtc = machine.RTC()
utc_shift = 1

tm = utime.localtime(utime.mktime(utime.localtime()) + utc_shift*3600)
tm = tm[0:3] + (0,) + tm[3:6] + (0,)
rtc.datetime(tm)
print("machine time is:",(utime.localtime()))
LED(0)