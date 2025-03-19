#Version 11

import gc
from log import logger
import machine
from machine import Pin, RTC
from mqtt_as import MQTTClient, RP2
from mqtt_local import config
import network
from ntptime import settime
import os
from ota import OTAUpdater
from stepper import Stepper
import sys
import uasyncio as asyncio
import time


if RP2:
    from sys import implementation
    

# define motor controller pins
s1 = Stepper(18,19,steps_per_rev=96000,speed_sps=1000)
disable = Pin(20, Pin.OUT)
endswitch = Pin(22, Pin.IN, Pin.PULL_UP)
alarm = Pin(17, Pin.IN, Pin.PULL_UP)
LED = machine.Pin("LED",machine.Pin.OUT)
rain = Pin(16, Pin.IN, Pin.PULL_UP)


# Default  MQTT_BROKER to connect to
#MQTT Details
CLIENT_ID = config["client_id"]
DEVICE_ID = config["device_id"]

SUBSCRIBE_TOPIC1 = str(CLIENT_ID)+"/set_angle"
SUBSCRIBE_TOPIC2 = str(CLIENT_ID)+"/status"
SUBSCRIBE_TOPIC3 = str(DEVICE_ID)+"/general"
PUBLISH_TOPIC1 = str(CLIENT_ID)+"/status"
PUBLISH_TOPIC2 = str(CLIENT_ID)+"/actPos"
PUBLISH_TOPIC3 = str(CLIENT_ID)+"/info"
PUBLISH_TOPIC4 = str(DEVICE_ID)+"/general"

# Global values
gc_text = ''
DATAFILENAME = 'data.txt'
LOGFILENAME = 'debug.log'
ERRORLOGFILENAME = 'errorlog.txt'



homingneeded = True
pos = 0
oldTime = 0
currentTime = 0
rssi = -199  # Effectively zero signal in dB.

html = """<!DOCTYPE html>
<html>
    <head> <title>Pergola controller #2</title> </head>
    <body> <h1>Pergola shading control #2</h1>
        <h3>%s</h3>
        <h4>%s</h4>
        <pre>%s</pre>
    </body>
</html>
"""


async def log_handling():

    local_time = time.localtime()
    global timestamp
    record("power-up @ (%d, %d, %d, %d, %d, %d, %d, %d)" % local_time)

    try:
        
        y = local_time[0]  # curr year
        mo = local_time[1] # current month
        d = local_time[2]  # current day
        h = local_time[3]  # curr hour
        m = local_time[4]  # curr minute
        s = local_time[5]  # curr second
        
        timestamp = f"{h:02}:{m:02}:{s:02}"
        # Test WiFi connection twice per minute
        if s in (15, 45):
            if not wifi_han(state):
                record(f"{timestamp} WiFi not connected")
                
            elif wifi_han(state):
                sync_rtc_to_ntp()
                time.sleep(1)
        
        # Print time on 30 min intervals
        if s in (1,) and not m % 30:
            try:
                record(f"datapoint @ {timestamp}")
                
                gc_text = f"free: {str(gc.mem_free())}\n"
                gc.collect()
            except Exception as e:
                with open(ERRORLOGFILENAME, 'a') as file:
                    file.write(f"error printing: {repr(e)}\n")

        # Once daily (during the wee hours)
        if h == 2 and m == 10 and s == 1:
            
            # Read lines from previous day
            with open(DATAFILENAME) as f:
                lines = f.readlines()

            # first line is yesterday's date
            yesterdate = lines[0].split()[-1].strip()

            # cull all lines containing '@'
            lines = [line
                     for line in lines
                     if '@' not in line]
            
            # Log lines from previous day
            with open(LOGFILENAME, 'a') as f:
                for line in lines:
                    f.write(line)
            
            # Start a new data file for today
            with open(DATAFILENAME, 'w') as file:
                file.write('Date: %d/%d/%d\n' % (mo, d, y))

    except Exception as e:
        with open(ERRORLOGFILENAME, 'a') as file:
            file.write(f"main loop error: {str(e)}\n")



async def serve_client(reader, writer):
    
    
    try:
        print("Client connected")
        request_line = await reader.readline()
        print("Request:", request_line)
        
        # We are not interested in HTTP request headers, skip them
        while await reader.readline() != b"\r\n":
            pass

        version = f"MicroPython Version: {sys.version}"

        if '/log' in request_line.split()[1]:
            with open(LOGFILENAME) as file:
                data = file.read()
            heading = "Debug"
            print('log demanded')
        elif '/err' in request_line.split()[1]:
            with open(ERRORLOGFILENAME) as file:
                data = file.read()
            heading = "ERRORS"
        else:
            with open(DATAFILENAME) as file:
                data = file.read()
            heading = "Append '/log' or '/err' to URL to see log file or error log"

        data += gc_text

        response = html % (heading, version, data)
        writer.write('HTTP/1.0 200 OK\r\nContent-type: text/html\r\n\r\n')
        writer.write(response)

        await writer.drain()
        await writer.wait_closed()
        print("Client disconnected")
    except Exception as e:
        with open(ERRORLOGFILENAME, 'a') as file:
            
            file.write(f"serve_client error @ {timestamp}: {str(e)}\n")


def record(line):
    """Combined print and append to data file."""
    print(line)
    line += '\n'
    with open(DATAFILENAME, 'a') as file:
        file.write(line)

def dprint(*args):
        logger.debug(*args)

# Received messages from subscriptions will be delivered to this callback
def sub_cb(topic, msg, retained):
    global pos
    global raining
    
    if topic.decode() == SUBSCRIBE_TOPIC1:
        
        if not 0 <= int(msg.decode()) <= 36000:
            print(str(msg.decode() + " is no INT"))
            pos = 0
        else:
            pos = int(msg.decode())
    
    if not 'rain' in CLIENT_ID:
        
        if topic.decode() == SUBSCRIBE_TOPIC3:
            if msg.decode() == "Raining":
                raining = True
            else:
                raining = False
    
    dprint(str(topic + ": " + msg))
    time.sleep(1)   

# Demonstrate scheduler is operational.
async def heartbeat():
    s = True
    while True:
        await asyncio.sleep_ms(500)
        LED(s)
        s = not s

async def wifi_han(state):
    s = "rssi: {}dB"
    LED(not state)
    if state:
        dprint('Wifi is up')
        dprint(s.format(rssi))
    else:
        dprint('Wifi is down')    
    await asyncio.sleep(1)

async def get_rssi():
    global rssi
    s = network.WLAN()
    ssid = config["ssid"].encode("UTF8")
    #while True:
    try:
        while True:
            
            rssi = [x[3] for x in s.scan() if x[0] == ssid][0]
            
            break
        
    except IndexError:  # ssid not found.
        rssi = -199
    await asyncio.sleep(30)

async def get_ntp():
    
    try:
    
        settime()
        rtc = machine.RTC()
        utc_shift = 1

        tm = time.localtime(time.mktime(time.localtime()) + utc_shift*3600)
        tm = tm[0:3] + (0,) + tm[3:6] + (0,)
        rtc.datetime(tm)
    
    except OSError as e:
        with open(ERRORLOGFILENAME, 'a') as file:
            file.write(f"OSError while trying to set time: {str(e)}\n")        
        
    print("machine time is:",(time.localtime()))

#Inverse input
async def swap_io():
    
    global raining
    if 'rain' in CLIENT_ID:
        if rain():
            raining = False
        elif not rain():
            raining = True
    

# Homing sequence
async def homing(client):
    
    
    while True:
        await asyncio.sleep(1)
        dprint('Homing')

        await client.publish(PUBLISH_TOPIC1, f"Homing", qos=1)
        dprint("Homing")
        
        #Crash recovery
        if endswitch() and not alarm():
            await client.publish(PUBLISH_TOPIC1, f"Crash detected, recovery started", qos=1)
            dprint("Crash detected, recovery started")
            LED(1)
            s1.speed(1000) #use low speed for the calibration
             
            disable(0)
            s1.free_run(1)
            now = time.time()
            delay = 10
            while endswitch.value() == 1 and not alarm(): #wait till the switch is triggered
                if time.time() > now + delay:
                    s1.stop()
                    dprint("Changing direction")
                    break
                time.sleep(1)
                pass
            
            
            s1.free_run(-1) 
            now = time.time()
            delay = 10
            while endswitch.value() == 1 and not alarm(): #wait till the switch is triggered
                if time.time() > now + delay:
                    s1.stop()
                    disable(1)
                    dprint("Recovery failed! Entered sleep until reboot")
                    await client.publish(PUBLISH_TOPIC1, f"Recovery failed! Entered sleep until reboot", qos=1)
                    time.sleep(5)
                    machine.lightsleep()
                time.sleep(1)
                pass
            await client.publish(PUBLISH_TOPIC1, f"Recovery successful, homing started", qos=1)
            dprint("Recovery successful, start homing")
            
#Homing            
        if not endswitch() and not alarm():
            LED(1)
            s1.speed(500) #use low speed for the calibration
            s1.free_run(-1) #move backwards
            disable(0)
            while endswitch.value() == 0 and not alarm(): #wait till the switch is triggered
                pass
        
            s1.stop() #stop as soon as the switch is triggered
            s1.overwrite_pos(0) #set position as 0 point
            s1.target(0) #set the target to the same value to avoid unwanted movement
            await client.publish(PUBLISH_TOPIC2, str(s1.get_pos()), qos=1)
            homingneeded = False
            s1.free_run(1) #move forwards

            now = time.time()
            delay = 3
            while endswitch.value() == 1 and not alarm(): #wait till the switch is triggered
                if time.time() > now + delay:
                    s1.stop()
                    disable(1)
                    dprint("Homing failed!")
                    await client.publish(PUBLISH_TOPIC1, f"Homing failed!", qos=1)
                    time.sleep(5)
                    machine.soft_reset()
                pass
        
            time.sleep(0.1)        
            s1.stop() #stop as soon as the switch is triggered
            s1.overwrite_pos(0) #set position as 0 point
            s1.target(0) #set the target to the same value to avoid unwanted movement
            s1.speed(1000) #return to default speed
            s1.track_target() #start stepper again
            disable(1)
            await client.publish(PUBLISH_TOPIC1, f"Homing successful", qos=1)
            dprint("Homing successful")
            
        if alarm():
            await client.publish(PUBLISH_TOPIC1, f"DRIVE ALARM", qos=1)
            s1.stop()
            disable(1)
            dprint("DRIVE ALARM")
            await homing(client)
        LED(0)
        time.sleep(1)
        break

# Standard operating sequence
async def motion(client):
    
    updatepos = False
    updaterain = False
    s = "rssi: {}dB"
    

    while True and not alarm():
        await swap_io()
        gc.collect()
        m = gc.mem_free()
        await client.publish(PUBLISH_TOPIC3, s.format(rssi, m), qos=1)
        #await client.publish(PUBLISH_TOPIC2, str(s1.get_pos()), qos=1)
        
           
        if endswitch():
            s1.stop()
            disable(1)
                        
            if pos >= s1.get_pos():
                s1.free_run(-1)
                disable(0)
                now = time.time()
                delay = 3           
                while endswitch.value() == 1: #wait till the switch is triggered
                    if time.time() > now + delay:
                        dprint("Recovery failed")
                        await client.publish(PUBLISH_TOPIC1, f"Recovery failed!", qos=1)
                        s1.stop()
                        disable(1)
                        time.sleep(5)
                        sys.exit("Recovery failed!")
                    pass
                
            elif pos <= s1.get_pos():
                s1.free_run(1)
                disable(0)
                now = time.time()
                delay = 3           
                while endswitch.value() == 1: #wait till the switch is triggered
                    if time.time() > now + delay:
                        dprint("Recovery failed")
                        await client.publish(PUBLISH_TOPIC1, f"Recovery failed!", qos=1)
                        s1.stop()
                        disable(1)
                        time.sleep(5)
                        sys.exit("Recovery failed!")
                    pass
            time.sleep(0.5)
            s1.stop()
            
            await client.publish(PUBLISH_TOPIC1, f"Positioning error!", qos=1)
            dprint("Positioning error!")
            time.sleep(5)
            await homing(client)
            break
        
        elif s1.get_pos() != pos and not raining and not endswitch():
            disable(0)
            s1.target(pos)
            await client.publish(PUBLISH_TOPIC1, f"Moving from: " + str(s1.get_pos()) + " to "+ str(pos), qos=1)
            await client.publish(PUBLISH_TOPIC2, str(s1.get_pos()), qos=1)
            await client.publish(PUBLISH_TOPIC4, f"Ready", qos=1)
            dprint("Moving from: " + str(s1.get_pos()) + " to "+ str(pos))
            time.sleep(0.5)
            updatepos = True
            updaterain = False
            
        elif s1.get_pos() == pos and not raining and not endswitch() and updatepos:
            #dprint("Ready and no rain")
            disable(1)
            await client.publish(PUBLISH_TOPIC1, f"Ready", qos=1)
            await client.publish(PUBLISH_TOPIC2, str(s1.get_pos()), qos=1)
            await client.publish(PUBLISH_TOPIC4, f"Ready", qos=1)
            dprint("Ready")
            dprint(s.format(rssi))
            time.sleep(0.5)
            updatepos = False
            updaterain = False
            
        elif raining and not endswitch() and not updaterain:
            
            dprint("Raining")
            disable(0)
            s1.target(0)
            await client.publish(PUBLISH_TOPIC4, f"Raining", qos=1)
            time.sleep(0.5)
            updaterain = True
        
    while True and alarm():
        
            await client.publish(PUBLISH_TOPIC1, f"DRIVE ALARM", qos=1)
            s1.stop()
            disable(1)
            dprint("DRIVE ALARM")
            await homing(client)

async def OTA():
    global gc_text, tz_offset
    
    # Check for OTA updates
    repo_name = "PergolaPicoOTA"
    branch = "refs/heads/main/NoSensor"
    firmware_url = f"https://github.com/MartiMan79/{repo_name}/{branch}/"
    ota_updater = OTAUpdater(firmware_url,
                             "boot.py",
                             "main.py",
                             "ota.py",
                             "log.py",
                             "lib/ntptime.py",
                             "lib/logging/handlers.py",
                             "lib/logging/__init__.py",
                             "lib/stepper/__init__.py",
                             )
    ota_updater.download_and_install_update_if_available()     

async def main(client):

  
    try:
        await client.connect()
        await client.subscribe(SUBSCRIBE_TOPIC1, qos=1)
        await client.subscribe(SUBSCRIBE_TOPIC2, qos=1)
        await client.subscribe(SUBSCRIBE_TOPIC3, qos=1)
        await client.publish(PUBLISH_TOPIC3, f'Connected', qos=1)
        await client.publish(PUBLISH_TOPIC4, f'Ready', qos=1)
        await get_ntp()
        await OTA()
        dprint("Ready")
        
        
    except OSError:
        dprint('Connection failed.')
        return
    
    global homingneeded
    while True and homingneeded == True:
        await homing(client)
        break
    
    while True:
        await motion(client)
        

# Define configuration
config['subs_cb'] = sub_cb
config['wifi_coro'] = wifi_han
config['clean'] = True
config['will'] = (PUBLISH_TOPIC3, f'Lost connection', False, 0)
config['keepalive'] = 120


# Set up client
MQTTClient.DEBUG = True  # Optional
client = MQTTClient(config)


asyncio.create_task(heartbeat())
asyncio.create_task(get_rssi())
asyncio.create_task(log_handling())
asyncio.create_task(asyncio.start_server(serve_client, "0.0.0.0", 80))

try:
    asyncio.run(main(client))
    
finally:
    client.close()  # Prevent LmacRxBlk:1 errors
    asyncio.new_event_loop()
