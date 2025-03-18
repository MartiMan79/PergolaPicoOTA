from mqtt_as import config

config["server"] = "192.168.0.4"  # Change to suit

MACHINE_ID = "_pergola_no_sensor"
DEVICE_ID = "pico_w"
CLIENT_ID = str(DEVICE_ID)+str((MACHINE_ID))#[14:-1])

config["ssid"] = "SmeetsHome"
config["wifi_pw"] = "mm837283"
config["client_id"] = CLIENT_ID