#Version 4

import machine
from machine import Pin
from stepper import Stepper
import utime
from mqtt_as import MQTTClient
from mqtt_local import wifi_led, blue_led, config
import uasyncio as asyncio
import os


#Log declarations
rtc=machine.RTC()
#FileNameSys = 'syslog.txt'
FileName = 'log.txt'

#os.dupterm(open(FileNameSys, "a"))

# define motor controller pins

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
PUBLISH_TOPIC = str(CLIENT_ID)+"/status"

#Rain detection
#rain = Pin(16, Pin.IN, Pin.PULL_UP)

homingneeded = True
pos = 0
oldTime = 0
currentTime = 0
rain = False


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
        if not 0 <= int(msg.decode()) <= 34666:
            #log(str(msg.decode() + " is no INT"))
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



async def homing(client):
    
    try:
        await client.connect()
    except OSError:
        print('Connection failed.')
        return
    
    while True:
        await asyncio.sleep(1)
        log('Homing')
        #log(f"Begin connection with MQTT Broker :: {MQTT_BROKER}")
        #mqttClient = MQTTClient(CLIENT_ID, MQTT_BROKER, keepalive=60)
        await client.publish(PUBLISH_TOPIC, str("Homing").encode())
        
        
        LED_FileWrite(1)
        s1.speed(500) #use low speed for the calibration
        s1.free_run(-1) #move backwards
        disable(0)
        
        if not endswitch():
            while endswitch.value() == 0 and not alarm(): #wait till the switch is triggered
                pass
        else:
            disable(1)
            await client.publish(PUBLISH_TOPIC, str("Homing failed!").encode())
            log("Homing failed")
            return("Homing failed")    
        
        s1.stop() #stop as soon as the switch is triggered
        s1.overwrite_pos(0) #set position as 0 point
        s1.target(0) #set the target to the same value to avoid unwanted movement
    
        homingneeded = False
        s1.free_run(1) #move backwards
    
        while endswitch.value() == 1: #wait till the switch is triggered
            pass
    
        utime.sleep(0.1)        
        s1.stop() #stop as soon as the switch is triggered
        s1.overwrite_pos(0) #set position as 0 point
        s1.target(0) #set the target to the same value to avoid unwanted movement
        s1.speed(1000) #return to default speed
        s1.track_target() #start stepper again
        disable(1)
        await client.publish(PUBLISH_TOPIC, str("Homing Successful").encode())
        log("Homing Successful")
        
        if alarm():
            await client.publish(PUBLISH_TOPIC, str("DRIVE ALARM").encode())
            log("DRIVE ALARM")
            reset()
        LED_FileWrite(0)
        utime.sleep(1)
        break
        
    


async def main(client):
    try:
        await client.connect()
    except OSError:
        print('Connection failed.')
        return
        
    #log(f"Begin connection with MQTT Broker :: {MQTT_BROKER}")
    global homingneeded
    while True and homingneeded == True:
        await homing(client)
        break
    
    updatepos = False
    
    while True and not alarm():# and mqttClient.connect():
        # Non-blocking wait for message
        #log("Ready for operation")
        await client.subscribe(SUBSCRIBE_TOPIC1)
        await client.subscribe(SUBSCRIBE_TOPIC2)
    
        global rain
         
        if s1.get_pos() != pos and not rain and not endswitch():
            disable(0)
            s1.target(pos)
            await client.publish(PUBLISH_TOPIC, str("Moving").encode())
            log("Moving from: " + str(s1.get_pos()) + " to "+ str(pos))
            utime.sleep(0.5)
            updatepos = True
                        
        elif s1.get_pos() == pos and not rain and not endswitch() and updatepos:
            #log("Ready and no rain")
            disable(1)
            await client.publish(PUBLISH_TOPIC, str("Ready").encode())
            log("Ready")
            utime.sleep(0.5)
            updatepos = False
                    
        elif rain and not endswitch():
            #log("Raining")
            disable(0)
            s1.target(0)
            await client.publish(PUBLISH_TOPIC, str("Raining").encode())
            utime.sleep(0.5)
        
        elif endswitch():
            disable(1)
            await client.publish(PUBLISH_TOPIC, str("Positioning error!").encode())
            log("Positioning error!")
            utime.sleep(5)
            break
            
      
    while True and alarm():
        
        log("alarm")
        disable(1)
        await client.publish(PUBLISH_TOPIC, str("DRIVE alarm").encode())
        log("DRIVE alarm")
        utime.sleep(1)
        #reset()


# Define configuration
config['subs_cb'] = sub_cb
config['wifi_coro'] = wifi_han
config['clean'] = False
#config['will'] = ('Info/result', f'Lost connection', False, 0)
config['keepalive'] = 120

# Set up client
MQTTClient.DEBUG = False  # Optional
client = MQTTClient(config)

asyncio.create_task(heartbeat())
try:
    asyncio.run(main(client))
    
finally:
    client.close()  # Prevent LmacRxBlk:1 errors
    asyncio.new_event_loop()

