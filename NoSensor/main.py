#Version 2

import machine
from machine import Pin
from stepper import Stepper
import utime
import ubinascii
from umqtt.simple import MQTTClient
import os
import sys

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
MQTT_BROKER = "rpi4.local"
MACHINE_ID = "_rain_sensor"
DEVICE_ID = "pico_w"
CLIENT_ID = str(DEVICE_ID)#+str((MACHINE_ID))#[14:-1])
SUBSCRIBE_TOPIC1 = str(CLIENT_ID)+"/set_angle"
SUBSCRIBE_TOPIC2 = str(DEVICE_ID)+str(MACHINE_ID)+"/status"
PUBLISH_TOPIC = str(CLIENT_ID)+"/status"
mqttClient = MQTTClient(CLIENT_ID, MQTT_BROKER, keepalive=0)
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
def sub_cb(topic, msg):
    global pos
    global rain
    
    
        
    if topic.decode() == str(CLIENT_ID)+"/set_angle":
        #log("correct subscribe")
        if not 0 <= int(msg.decode()) <= 34666:
            #log(str(msg.decode() + " is no INT"))
            pos = 0
        else:
            pos = int(msg.decode())
        
    elif topic.decode() == "status":
        if msg.decode() == "Raining":
            rain = True
        else:
            rain = False
    
    log(str(topic + ": " + msg))
    utime.sleep(1)   

def reset():
    log("Resetting...")
    utime.sleep(5)
    machine.reset()
 
def homing():
    log('Homing')
    log(f"Begin connection with MQTT Broker :: {MQTT_BROKER}")
    #mqttClient = MQTTClient(CLIENT_ID, MQTT_BROKER, keepalive=60)
    mqttClient.set_callback(sub_cb)
    mqttClient.connect()
    mqttClient.publish(PUBLISH_TOPIC, str("Homing").encode())
    
    s1.speed(500) #use low speed for the calibration
    s1.free_run(-1) #move backwards
    disable(0)
    if not endswitch():
        while endswitch.value() == 0 and not alarm(): #wait till the switch is triggered
            pass
    else:
        disable(1)
        mqttClient.publish(PUBLISH_TOPIC, str("Homing failed!").encode())
        log("Homing failed")
        sys.exit("Homing failed")    
        
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
    mqttClient.publish(PUBLISH_TOPIC, str("Homing Successful").encode())
    log("Homing Successful")
    if alarm():
        mqttClient.publish(PUBLISH_TOPIC, str("DRIVE ALARM").encode())
        log("DRIVE ALARM")
    
    utime.sleep(1)
    


def main(blocking_method=False):
    log(f"Begin connection with MQTT Broker :: {MQTT_BROKER}")
    #mqttClient = MQTTClient(CLIENT_ID, MQTT_BROKER, keepalive=90)
    mqttClient.set_callback(sub_cb)
    mqttClient.connect()
    mqttClient.subscribe(SUBSCRIBE_TOPIC1)
    mqttClient.subscribe(SUBSCRIBE_TOPIC2)
    log(f"Connected to MQTT  Broker :: {MQTT_BROKER}, and waiting for callback function to be called!")
    previousState = False
    updatepos = False
        
    while True and not alarm():# and mqttClient.connect():
        # Non-blocking wait for message
        #log("Ready for operation")
        
        
        global rain
        
        if blocking_method:
            mqttClient.wait_msg()
        else:
            mqttClient.check_msg()
            utime.sleep(1)
            
        if s1.get_pos() != pos and not rain and not endswitch():
            disable(0)
            s1.target(pos)
            mqttClient.publish(PUBLISH_TOPIC, str("Moving").encode())
            log("Moving from: " + str(s1.get_pos()) + " to "+ str(pos))
            utime.sleep(0.5)
            updatepos = True
                        
        elif s1.get_pos() == pos and not rain and not endswitch() and updatepos:
            #log("Ready and no rain")
            disable(1)
            mqttClient.publish(PUBLISH_TOPIC, str("Ready").encode())
            log("Ready")
            utime.sleep(0.5)
            updatepos = False
                    
        elif rain and not endswitch():
            #log("Raining")
            disable(0)
            s1.target(0)
            mqttClient.publish(PUBLISH_TOPIC, str("Raining").encode())
            utime.sleep(0.5)
        
        elif endswitch():
            disable(1)
            mqttClient.publish(PUBLISH_TOPIC, str("Positioning error!").encode())
            log("Positioning error!")
            
            utime.sleep(1)
            if pos <= 10000:
                log("error needs homing")
                homing()
                utime.sleep(1)
                break
                
            
            elif pos >= 10000:
                log("moving back")
                s1.speed(500) #use low speed for the calibration
                s1.free_run(-1) #move backwards
                disable(0)
                
                while endswitch.value() == 1: #wait till the switch is triggered
                    pass
                
                utime.sleep(0.1)        
                s1.stop() #stop as soon as the switch is triggered
                utime.sleep(1)
                log("error needs homing")
                homing()
                utime.sleep(1)
                break
        
    

  
    while True and alarm():
        log("alarm")
        disable(1)
        mqttClient.publish(PUBLISH_TOPIC, str("DRIVE alarm").encode())
        log("DRIVE alarm")
        utime.sleep(1)


if homingneeded == True:
                homing()    

if __name__ == "__main__":
    
    while True:
        
        try:
            main()
            
            
                            
        except OSError as e:
            log("Error: " + str(e))
            reset()
        except KeyboardInterrupt:
            reset()
