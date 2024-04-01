
# https://github.com/agners/micropython-scd30

import network, usocket, ustruct, utime, machine
import ntptime
import time
from machine import I2C, Pin
from time import sleep
import ubinascii
from umqttsimple import MQTTClient
import json
from machine import WDT
import config
import utime

# AP info
SSID=config.ssid # Network SSID
KEY=config.key  # Network key

TIMESTAMP = 2208988800

mqtt_server = config.mqtt_server

client_id = ubinascii.hexlify(machine.unique_id()).decode('utf-8')
topic_sub = config.topic_sub
topic_pub = config.topic_pub

last_message = 0
message_interval = 30 # in seconds

led = Pin(13, Pin.OUT)
#red = Pin(25, Pin.OUT)
#green = Pin(17, Pin.OUT)
#blue = Pin(18, Pin.OUT)
kwhA = 0.0
kwhB = 0.0

# data is collected to this
data = {}

# Nimi, tyyppi, arvo
# infos = {
#     "bme_hum": [ "Kosteus", "humidity", "%" ],
#     "bme_temp": [ "Lmptila (BME680)", "temperature", "C" ],
#     "bme_gas": [ "Orgaaniset yhdisteet", "volatile_organic_compounds", "ohm" ],
#     "bme_pres": [ "Ilmanpaine", "pressure", "mBar" ],
#     "scd30_co2": [ "Hiilidioksidi (co2)", "carbon_dioxide", "ppm" ],
#     "scd30_temp": [ "Lmptila (SCD30)", "temperature", "C" ],
#     "scd30_relhum": [ "Suhteellinen kosteus", "humidity", "%" ],
#     "start_time": [ "Kynnistysaika", "timestamp", "timestamp" ]
#     }

infos = {
    "powerA": [ "Pajan sähköteho", "power", "W", None ],
    "powerB": [ "Autojen sähköteho", "power", "W", None ],
    "energyA": [ "Pajan sähkönkulutus", "energy", "kWh", "total_increasing" ],
    "energyB": [ "Autojen sähkönkulutus", "energy", "kWh", "total_increasing" ],
    "start_time": [ "Käynnistynyt", None, None, None ],
    "heartbeat": [ "Viimeisin viesti", None, None, None ]
    }
#    "start_time": [ "Startup time", "timestamp", "timestamp" ],
#    "heartbeat": [ "Heartbeat", "timestamp", "timestamp" ]

# are sensors registered to Home Assistant already
discovery_topics_sent = {}

# ISO 8601 time format
def format_time_to_iso(t):
    return "{:04d}-{:02d}-{:02d}T{:02d}:{:02d}:{:02d}Z".format(t[0], t[1], t[2], t[3], t[4], t[5])

def led_on():
    led.high()

def led_off():
    led.low()
    
# 
# def led_red():
#     global red#, green, blue
#     red.value(1)
# #    blue.value(0)
# #    green.value(0)
# 
# def led_off():
#     global red#, green, blue
#     red.value(0)
# #    blue.value(0)
# #    green.value(0)
# 
# def led_blue():
#     global red, green, blue
#     red.value(0)
#     blue.value(1)
#     green.value(0)
# 
# def led_green():
#     global red, green, blue
#     red.value(0)
#     blue.value(0)
#     green.value(1)
# 
# def led_yellow():
#     global red, green, blue
#     red.value(0)
#     blue.value(1)
#     green.value(1)

def connect_wifi():
    
    global wdt
    global usewdt

    tryagain = 1
    led_off()
    # Init wlan module and connect to network
    while (tryagain < 5):
        try:
            print("Trying to connect to wifi... 10 sec")
            print("{} {}".format(SSID,KEY))
            led_on()
            if (usewdt):
                 wdt.feed()
            wlan = network.WLAN()
            wlan.active(True)
            wlan.connect(SSID, key=KEY, security=wlan.WPA_PSK)
            cnt = 0
            while wlan.isconnected() == False:
                cnt = cnt + 1
                print(".", end='')
                led_off()
                time.sleep_ms(100)
                if (usewdt):
                    wdt.feed()
                led_on()
                time.sleep_ms(100)

                if (cnt>100):
                    print("no response for 10sec, bailout waiting")
                    break # exit loop if over 10 sec wait

            print("WLAN STATUS {}".format(wlan.isconnected()))
            # We should have a valid IP now via DHCP
            print(wlan.ifconfig())
            led_off()
            break
        except:
            print ("Can't connect to wifi, trying again")
            if (usewdt):
                wdt.feed()
            led_off()
            sleep(1)
            tryagain = tryagain + 1
            #if (tryagain>5):
            #    restart_and_reconnect()
    
def ntp():
    global data
    global wdt
    global usewdt
    
    if (usewdt):
        wdt.feed()

    print("Local time before synchronization：%s" %str(time.localtime()))
    ntptime.timeout = 10
    ntptime.settime()
    print("Local time after synchronization：%s" %str(time.localtime()))
    data['start_time'] = str(time.localtime())

def ntpOld():
    global data
    global wdt
    global usewdt
    
    if (usewdt):
        wdt.feed()

    # Create new socket
    client = usocket.socket(usocket.AF_INET, usocket.SOCK_DGRAM)
    client.bind(("", 8080))
    #client.settimeout(3.0)

    # Get addr info via DNS
    addr = usocket.getaddrinfo("pool.ntp.org", 123)[0][4]
    if (usewdt):
        wdt.feed()

    # Send query
    client.sendto('\x1b' + 47 * '\0', addr)
    datafromclient, address = client.recvfrom(1024)

    # Print time
    t = ustruct.unpack(">IIIIIIIIIIII", datafromclient)[10] - TIMESTAMP
    s = "%d-%d-%dT%d:%d:%d" % utime.localtime(t)[0:6]
    print(s)
    data['start_time'] = s # secs
#    print ("%d-%d-%d %d:%d:%d" % (utime.localtime(t)[0:6]))


def scan_i2c():
#     Scanning bus 0...
#     Found device at address 0:0x60
#     Found device at address 0:0x61 <- scd30 ilmanlaatusensori
#     Found device at address 0:0x6a
# 
#     Scanning bus 1...

    i2c_list    = [None, None]
    i2c_list[0] = I2C(0, scl=Pin(13), sda=Pin(12), freq=100_000)
    i2c_list[1] = I2C(1, scl=Pin(7), sda=Pin(6), freq=100_000)

    for bus in range(0, 2):

        print("\nScanning bus %d..."%(bus))

        for addr in i2c_list[bus].scan():
            print("Found device at address %d:0x%x" %(bus, addr))

def sub_cb(topic, msg):
  print((topic, msg))
  if msg == b'reboot':
      restart_and_reconnect()
      
  if topic == b'notification' and msg == b'received':
    print('ESP received hello message')
        
def connect_and_subscribe():
  global client_id, mqtt_server, topic_sub, topic_pub
  print("creating mqtt client 1883")
  client = MQTTClient(client_id, mqtt_server, port=1883, ssl=False, user=config.mqtt_user, password=config.mqtt_password)
  client.set_callback(sub_cb)
  print("connecting mqtt client user='%s' pwd='%s' client_id='%s' server='%s'" % (config.mqtt_user, config.mqtt_password, client_id, mqtt_server))
  client.connect()
  print("subscribing mqtt client")
  client.subscribe(topic_sub)
  print('Connected to %s MQTT broker, subscribed to %s topic' % (mqtt_server, topic_sub))
  msg = b'%s' % 'Client ' + client_id + ' started'                 
  client.publish(topic_pub, msg)

  return client

def restart_and_reconnect():
  print('Omitting rebooting...')
  led_off()
  #time.sleep(1)
  #machine.reset()


# Initialize the impulse counter and the last measurement time
impulse_counterA = 0
last_measurement_timeA = utime.ticks_ms()
impulse_counterB = 0
last_measurement_timeB = utime.ticks_ms()

# This function will be called every time an impulse is detected
def handle_impulseA(pin):
    global impulse_counterA
    impulse_counterA += 1
    print("Impulse A detected")

# This function will be called every time an impulse is detected
def handle_impulseB(pin):
    global impulse_counterB
    impulse_counterB += 1
    print("Impulse B detected")

# Set up the pin connected to the electricity meter to call handle_impulse on the rising edge
impulse_pinA = Pin('D12', mode=Pin.IN, pull=Pin.PULL_UP)  # Replace 'P10' with the correct pin
impulse_pinA.irq(trigger=Pin.IRQ_RISING, handler=handle_impulseA)

# Set up the pin connected to the electricity meter to call handle_impulse on the rising edge
impulse_pinB = Pin('D10', mode=Pin.IN, pull=Pin.PULL_UP)  # Replace 'P10' with the correct pin
impulse_pinB.irq(trigger=Pin.IRQ_RISING, handler=handle_impulseB)

# main program starts here

def main():
    global impulse_counterA
    global last_measurement_timeA
    global impulse_counterB
    global last_measurement_timeB
    global message_interval
    global last_message
    global data
    global client_id, mqtt_server, topic_sub, topic_pub
    global wdt
    global usewdt
    global config
    global kwhA
    global kwhB

    print("Led ON")
    led_on()
    sleep(1)
    print("Led OFF")
    led_off()
    sleep(1)

    # shall we use watchdog ?
    usewdt = True
    
    if (usewdt):
        wdt = WDT(timeout=8000)  # enable it with a timeout of 8s

    scan_i2c()

    connect_wifi()

    try:
      client = connect_and_subscribe()
    except OSError as e:
      restart_and_reconnect()

    print("Getting date and time")
    ntp()
    print("NTP OK")
    data['heartbeat'] = time.localtime()
    if (usewdt):
        wdt.feed()

    startup_time = time.time()
    reset_when_up_more_than_seconds = 60 * 10 #* 4 # 4h reset interval
    impulse_counterA = 0
    last_measurement_timeA = utime.ticks_ms()
    impulse_counterB = 0
    last_measurement_timeB = utime.ticks_ms()

    while True:
      try:
        client.check_msg()
        print(".", end='')
        since_last_message = (time.time() - last_message)
        
        #if (time.time() - startup_time) > reset_when_up_more_than_seconds:
        #    print("Restarting due to uptime")
        #    restart_and_reconnect()
            
        if since_last_message > message_interval:
          if (usewdt):
            wdt.feed()

          #timestamp = utime.localtime()
          data['heartbeat'] = time.localtime()

          # Calculate the time difference in hours since the last measurement
          time_diffA = utime.ticks_diff(utime.ticks_ms(), last_measurement_timeA) / (60 * 60 * 1000)

          #if time_diff >= 0:  # If at least one hour has passed
          # Calculate the power in kilowatts
          print("Time diff A: %.2f h" % time_diffA)
          print("Impulse counter A: %d" % impulse_counterA)
          print("Last measurement time: %d" % last_measurement_timeA)
          print("Current time: %d" % utime.ticks_ms())
          pulses_per_kwh = 1000  # Number of impulses per kilowatt-hour
          powerA = round(impulse_counterA / (pulses_per_kwh * time_diffA) * 1000, 2)  # Power in watts
          data['powerA'] = powerA
          print("Power A: %.0f W" % powerA)

          # Reset the impulse counter and the last measurement time
          impulse_counterA = 0
          last_measurement_timeA = utime.ticks_ms()

          # Calculate the time difference in hours since the last measurement
          time_diffB = utime.ticks_diff(utime.ticks_ms(), last_measurement_timeB) / (60 * 60 * 1000)

          #if time_diff >= 0:  # If at least one hour has passed
          # Calculate the power in kilowatts
          print("Time diff B: %.2f h" % time_diffB)
          print("Impulse counter B: %d" % impulse_counterB)
          print("Last measurement time: %d" % last_measurement_timeB)
          print("Current time: %d" % utime.ticks_ms())
          pulses_per_kwh = 1000  # Number of impulses per kilowatt-hour
          powerB = round(impulse_counterB / (pulses_per_kwh * time_diffB) * 1000, 2)  # Power in watts
          data['powerB'] = powerB
          print("Power B: %.0f W" % powerB)

          # Reset the impulse counter and the last measurement time
          impulse_counterB = 0
          last_measurement_timeB = utime.ticks_ms()

          # Calculate the energy consumption in kilowatt-hours
          kwhAnew = powerA * time_diffA / 1000  # Energy consumption in kilowatt-hours
          kwhBnew = powerB * time_diffB / 1000  # Energy consumption in kilowatt-hours
          kwhA = kwhA + kwhAnew
          kwhB = kwhB + kwhBnew
          
          print("Energy A: %.5f kWh" % kwhA)
          print("Energy B: %.5f kWh" % kwhB)

          data['energyA'] = kwhA
          data['energyB'] = kwhB

          #read_bme680()
          #read_scd30()
          led_on()
          print("Sending mqtt messages")
          #wdt.feed()

          for key in data:
             if (usewdt):
               wdt.feed()

             #topic_id = b'#%s_#%s' % (str(key), str(client_id))
             print("Key {}".format(key))

             info = infos[key]
             nimi = info[0]
             devclass = info[1]
             unitofmeasurement = info[2]
             state_class = info[3]
             
             uid = str(client_id) + "_" + str(key)

             #topic_id =  "homeassistant/sensor/ilmanlaatu" + "/" + str(client_id) + "/" + str(key)
             topic_id =  "homeassistant/sensor/" + str(topic_pub) + "/" + str(client_id) + "/" + str(key)

             print(topic_id, ":", key, '->', data[key])
             # https://www.home-assistant.io/integrations/mqtt#mqtt-discovery
             if (nimi in discovery_topics_sent) == False:
                 print("Sending MQTT sensor configuration message " + key)
                 #topic_discovery = "homeassistant/sensor/" + names[key] + "/config" #"homeassistant/sensor/ilmanlaatu/config"
                 topic_discovery = "homeassistant/sensor/" + str(client_id) + "_" + str(key) + "/config"
                 #"unique_id": ha_id,
                 # $ mosquitto_pub -t "homeassistant/sensor/abc/config" -m '{"state_topic": "homeassistant/sensor/abc/state", "value_template": "{{ value_json.temperature}}", "name": "temp sensor"}'
                 devpl = { "name": config.device_name,
                         "identifiers": client_id,
                         "manufacturer": config.manufacturer
                         }
                 
                 devplj = json.dumps(devpl).encode('utf-8')

    #              d1 = { "name": names[key],
    #                     "identifiers": "A",
    #                     "manufacturer": "DIY"
    #                     }
    #              
    #              msg = {
    #                  "device": d1,
    #                  "device_class": "sensor",
    #                  "name": names[key],
    #                  "state_topic": topic_id,
    #                  "value_template": "{{ value_json }}"
    #                  }
    #              
    # "device_class": "gas",
                 if devclass == None:
                     msg = b'{ "dev": '+ devplj +', "unique_id": "'+ uid +'", "state_topic": "' + topic_id + '", "value_template": "{{ value_json.value }}", "name": "'+ nimi +'"}'
                 else:
                     # energiamittareissa total_increasing esim.
                     if state_class != None:
                         msg = b'{ "dev": '+ devplj +', "unique_id": "'+ uid +'", "unit_of_measurement": "'+ unitofmeasurement + '", "device_class": "'+ devclass +'", "state_topic": "' + topic_id + '", "value_template": "{{ value_json.value }}", "name": "'+ nimi +'", "state_class": "'+ state_class +'"}'
                     else:
                         msg = b'{ "dev": '+ devplj +', "unique_id": "'+ uid +'", "unit_of_measurement": "'+ unitofmeasurement + '", "device_class": "'+ devclass +'", "state_topic": "' + topic_id + '", "value_template": "{{ value_json.value }}", "name": "'+ nimi +'"}'
                 #msg = b'{ "dev": '+ devplj +', "unique_id": "'+ uid +'", "unit_of_measurement": "'+ unitofmeasurement + '", "device_class": "'+ devclass +'", "state_topic": "' + topic_id + '", "name": "'+ nimi +'"}'
                 client.publish(topic_discovery, msg)
                 discovery_topics_sent[nimi] = True
    #             bme_gas/50159300689c611c
                 
    #          - name: "Ilmanlaatu co2 (A)"
    #      state_topic: "scd_co2/50159300689c611c"
    #      unit_of_measurement: "ppm"
    #      value_template: "{{ value_json }}"
             if key == "start_time" or key == "heartbeat":
                msg = b'{ "value": "'+ str(data[key]) + '"}'
             else:
                msg = b'{ "value": %.1f}' % data[key]
             print("Sending JSON mqtt message {} {}".format(topic_id, msg))
             client.publish(topic_id, msg)
             #if key == "start_time" or key == "heartbeat":
             #  #msg = b'{ "' + str(key) + '": "'+ str(data[key]) + '"}'
             #  msg = b'{ "value": "'+ str(data[key]) + '"}'
             #  print("Sending JSON mqtt message {} {}".format(topic_id, msg))
             #  client.publish(topic_id, msg)
             #else:
             #  msg = b'%.1f' % data[key]
             #  print("Sending FLOAT mqtt message {} {}".format(topic_id, msg))
             #  client.publish(topic_id, msg)
             #sleep(0.2)
          #msg = b'Hello #%d' % counter
          #client.publish(topic_pub, msg)
          led_off()
       
          last_message = time.time()
          print("Ok, sent")
          
      except OSError as e:
        led_off()
        print("Error #%s", (e))
        restart_and_reconnect()
        
        
      sleep(1)
      led_on()
      sleep(1)
      led_off()
      if (usewdt):
          wdt.feed()


# Micropython directly can be called without
#  if __name__ == "__main__":
main()