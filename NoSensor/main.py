#Version 9

import machine
import network
import gc
from machine import Pin
from stepper import Stepper
import utime
from mqtt_as import MQTTClient, RP2
from mqtt_local import wifi_led, blue_led, config
import uasyncio as asyncio
import os

if RP2:
    from sys import implementation
    
#Log declarations
rtc=machine.RTC()
FileName = 'log.txt'


# define motor controller pins
s1 = Stepper(18,19,steps_per_rev=96000,speed_sps=1000)
disable = Pin(20, Pin.OUT)
endswitch = Pin(22, Pin.IN, Pin.PULL_UP)
alarm = Pin(17, Pin.IN, Pin.PULL_UP)
LED_FileWrite = machine.Pin("LED",machine.Pin.OUT)

# Default  MQTT_BROKER to connect to
#MQTT Details
CLIENT_ID = config["client_id"]

SUBSCRIBE_TOPIC1 = str(CLIENT_ID)+"/set_angle"
SUBSCRIBE_TOPIC2 = str(CLIENT_ID)+"/status"
PUBLISH_TOPIC1 = str(CLIENT_ID)+"/status"
PUBLISH_TOPIC2 = str(CLIENT_ID)+"/actPos"
PUBLISH_TOPIC3 = str(CLIENT_ID)+"/info"

#Rain detection
#rain = Pin(16, Pin.IN, Pin.PULL_UP)

homingneeded = True
pos = 0
oldTime = 0
currentTime = 0
rain = False
rssi = -199  # Effectively zero signal in dB.

#Logging
try:
    os.stat(FileName)
    print("File Exists")
except:
    print("File Missing")
    f = open(FileName, "w")
    f.close()
    
def log(loginfo:str):
    # Format the timestamp
    LED_FileWrite(1)
    timestamp=rtc.datetime()
    timestring="%04d-%02d-%02d %02d:%02d:%02d"%(timestamp[0:3] + timestamp[4:7])
    # Check the file size
    filestats = os.stat(FileName)
    filesize = filestats[6]
    LED_FileWrite(0)

    if(filesize<200000):
        try:
            
            log = timestring +" "+ str(filesize) +" "+ loginfo +"\n"
            print(log)
            with open(FileName, "at") as f:
                f.write(log)
            
        except:
            print("Problem saving file")


# Received messages from subscriptions will be delivered to this callback
def sub_cb(topic, msg, retained):
    global pos
    global rain
    
    if topic.decode() == SUBSCRIBE_TOPIC1:
        #log("correct subscribe")
        if not 0 <= int(msg.decode()) <= 36000:
            print(str(msg.decode() + " is no INT"))
            pos = 0
        else:
            pos = int(msg.decode())
        
    elif topic.decode() == SUBSCRIBE_TOPIC2:
        if msg.decode() == "Raining":
            rain = True
        else:
            rain = False
    
    log(str(topic + ": " + msg))
    utime.sleep(1)   

# Demonstrate scheduler is operational.
async def heartbeat():
    s = True
    while True:
        await asyncio.sleep_ms(500)
        blue_led(s)
        s = not s

async def wifi_han(state):
    wifi_led(not state)
    print('Wifi is ', 'up' if state else 'down')
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
        

# Homing sequence
async def homing(client):
    
    
    while True:
        await asyncio.sleep(1)
        log('Homing')

        await client.publish(PUBLISH_TOPIC1, f"Homing", qos=1)
        
        if endswitch():
            
            disable(1)
            await client.publish(PUBLISH_TOPIC1, f"Homing failed!", qos=1)
            log("Homing failed")
            return("Homing failed")
        
        if not endswitch():
            LED_FileWrite(1)
            s1.speed(500) #use low speed for the calibration
            s1.free_run(-1) #move backwards
            disable(0)
        
        
            while endswitch.value() == 0 and not alarm(): #wait till the switch is triggered
                pass
        
            
        
        s1.stop() #stop as soon as the switch is triggered
        s1.overwrite_pos(0) #set position as 0 point
        s1.target(0) #set the target to the same value to avoid unwanted movement
        await client.publish(PUBLISH_TOPIC2, str(s1.get_pos()), qos=1)
        homingneeded = True
        s1.free_run(1) #move forwards
    
        while endswitch.value() == 1: #wait till the switch is triggered
            pass
    
        utime.sleep(0.1)        
        s1.stop() #stop as soon as the switch is triggered
        s1.overwrite_pos(0) #set position as 0 point
        s1.target(0) #set the target to the same value to avoid unwanted movement
        s1.speed(1000) #return to default speed
        s1.track_target() #start stepper again
        disable(1)
        await client.publish(PUBLISH_TOPIC1, f"Homing Successful", qos=1)
        log("Homing Successful")
        
        if alarm():
            await client.publish(PUBLISH_TOPIC1, f"DRIVE ALARM", qos=1)
            log("DRIVE ALARM")
            machine.reset()
        LED_FileWrite(0)
        utime.sleep(1)
        break

# Standard operating sequence
async def motion(client):
    
    updatepos = False
    s = "rssi: {}dB free: {}"
    print('rssi: ',rssi)

    while True and not alarm():
        
        gc.collect()
        m = gc.mem_free()

        await client.publish(PUBLISH_TOPIC3, s.format(rssi, m), qos=1)
        #await client.publish(PUBLISH_TOPIC2, str(s1.get_pos()), qos=1)
        global rain
         
        if endswitch():
            disable(1)
            s1.stop()
            
            if pos >= s1.get_pos():
                s1.free_run(-1)
                disable(0)
                while endswitch.value() == 1: #wait till the switch is triggered
                    pass
                
            elif pos <= s1.get_pos():
                s1.free_run(1)
                disable(0)
                while endswitch.value() == 1: #wait till the switch is triggered
                    pass
            utime.sleep(0.5)
            s1.stop()
            
            await client.publish(PUBLISH_TOPIC1, f"Positioning error!", qos=1)
            log("Positioning error!")
            utime.sleep(5)
            await homing(client)
            break
        
        elif s1.get_pos() != pos and not rain and not endswitch():
            disable(0)
            s1.target(pos)
            await client.publish(PUBLISH_TOPIC1, f"Moving", qos=1)
            await client.publish(PUBLISH_TOPIC2, str(s1.get_pos()), qos=1)
            log("Moving from: " + str(s1.get_pos()) + " to "+ str(pos))
            utime.sleep(0.5)
            updatepos = True
            
        
            
        elif s1.get_pos() == pos and not rain and not endswitch() and updatepos:
            #log("Ready and no rain")
            disable(1)
            await client.publish(PUBLISH_TOPIC1, f"Ready", qos=1)
            await client.publish(PUBLISH_TOPIC2, str(s1.get_pos()), qos=1)
            log("Ready")
            utime.sleep(0.5)
            updatepos = False
                    
        elif rain and not endswitch():
            #log("Raining")
            disable(0)
            s1.target(0)
            await client.publish(PUBLISH_TOPIC1, f"Raining", qos=1)
            utime.sleep(0.5)
        
        
    
    while True and alarm():
        
        log("alarm")
        disable(1)
        await client.publish(PUBLISH_TOPIC1, f"DRIVE alarm", qos=1)
        log("DRIVE alarm")
        utime.sleep(1)
        machine.reset()



async def main(client):

    try:
        await client.connect()
        await client.subscribe(SUBSCRIBE_TOPIC1, qos=1)
        await client.subscribe(SUBSCRIBE_TOPIC2, qos=1)
        await client.publish(PUBLISH_TOPIC3, f'Connected', qos=1)
    except OSError:
        print('Connection failed.')
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
try:
    asyncio.run(main(client))
    
finally:
    client.close()  # Prevent LmacRxBlk:1 errors
    asyncio.new_event_loop()




