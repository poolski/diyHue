import json
import logManager
import requests

logging = logManager.logger.get_logger(__name__)

def set_light(light, data):
    url = "http://" + light.protocol_cfg["ip"] + "/api/" + light.protocol_cfg["hueUser"] + "/lights/" + light.protocol_cfg["id"] + "/state"
    payload = {}
    payload.update(data)
    color = {}
    if "xy" in payload:
        color["xy"] = payload["xy"]
        del(payload["xy"])
    elif "ct" in payload:
        color["ct"] = payload["ct"]
        del(payload["ct"])
    elif "hue" in payload:
        color["hue"] = payload["hue"]
        del(payload["hue"])
    elif "sat" in payload:
        color["sat"] = payload["sat"]
        del(payload["sat"])
    if len(payload) != 0:
        requests.put(url, json=payload, timeout=3)
    if len(color) != 0:
        requests.put(url, json=color, timeout=3)

def get_light_state(light):
    state = requests.get("http://" + light.protocol_cfg["ip"] + "/api/" + light.protocol_cfg["hueUser"] + "/lights/" + light.protocol_cfg["id"], timeout=3)
    return state.json()["state"]

def discover(detectedLights, credentials):
    if "hueUser" in credentials and len(credentials["hueUser"]) > 32:
        logging.debug("hue: <discover> invoked!")
        try:
            response = requests.get("http://" + credentials["ip"] + "/api/" + credentials["hueUser"] + "/lights", timeout=3)
            if response.status_code == 200:
                logging.debug(response.text)
                lights = json.loads(response.text)
                for id, light in lights.items():
                    modelid = "LCT015"
                    if light["type"] == "Dimmable light":
                        modelid = "LWB010"
                    elif light["type"] == "Color temperature light":
                        modelid = "LTW001"
                    elif light["type"] == "On/Off plug-in unit":
                        modelid = "LOM001"
                    elif light["type"] == "Color light":
                        modelid = "LLC010"
                    detectedLights.append({"protocol": "hue", "name": light["name"], "modelid": modelid, "protocol_cfg": {"ip": credentials["ip"], "hueUser": credentials["hueUser"], "modelid": light["modelid"], "id": id, "uniqueid": light["uniqueid"]}})
        except Exception as e:
            logging.info("Error connecting to Hue Bridge: %s", e)

def discover_sensors(credentials):
    """Discover sensors (switches, buttons, motion sensors, etc.) from upstream Hue Bridge"""
    # Import here to avoid circular dependency
    import configManager
    from HueObjects import Sensor
    from functions.core import nextFreeId
    bridgeConfig = configManager.bridgeConfig.yaml_config
    
    if "hueUser" in credentials and len(credentials["hueUser"]) > 32:
        logging.debug("hue: <discover_sensors> invoked!")
        try:
            response = requests.get("http://" + credentials["ip"] + "/api/" + credentials["hueUser"] + "/sensors", timeout=3)
            if response.status_code == 200:
                logging.debug("Discovered sensors from Hue Bridge")
                sensors = json.loads(response.text)
                discovered_count = 0
                for id, sensor in sensors.items():
                    # Skip built-in sensors like Daylight
                    if sensor["type"] in ["Daylight", "CLIP"]:
                        continue
                    
                    # Check if sensor already exists (by uniqueid)
                    sensor_exists = False
                    if "uniqueid" in sensor:
                        for key, existing_sensor in bridgeConfig["sensors"].items():
                            if hasattr(existing_sensor, 'uniqueid') and existing_sensor.uniqueid == sensor["uniqueid"]:
                                sensor_exists = True
                                logging.debug(f"Sensor {sensor['name']} already exists, skipping")
                                break
                    
                    if sensor_exists:
                        continue
                    
                    # Create new sensor based on type
                    new_sensor_id = nextFreeId(bridgeConfig, "sensors")
                    
                    # Build sensor data
                    sensor_data = {
                        "id_v1": new_sensor_id,
                        "name": sensor["name"],
                        "type": sensor["type"],
                        "modelid": sensor["modelid"],
                        "manufacturername": sensor.get("manufacturername", "Philips"),
                        "swversion": sensor.get("swversion", "1.0"),
                        "uniqueid": sensor.get("uniqueid", ""),
                        "state": sensor.get("state", {}),
                        "config": sensor.get("config", {}),
                        "protocol": "hue",
                        "protocol_cfg": {
                            "ip": credentials["ip"],
                            "hueUser": credentials["hueUser"],
                            "id": id
                        }
                    }
                    
                    # Create and add the sensor
                    bridgeConfig["sensors"][new_sensor_id] = Sensor.Sensor(sensor_data)
                    discovered_count += 1
                    logging.info(f"Added sensor from Hue Bridge: {sensor['name']} (type: {sensor['type']}, model: {sensor['modelid']})")
                
                logging.info(f"Discovered {discovered_count} new sensors from upstream Hue Bridge")
        except Exception as e:
            logging.info("Error discovering sensors from Hue Bridge: %s", e)

def get_sensor_state(sensor):
    """Get current state of a sensor from upstream Hue Bridge"""
    try:
        url = "http://" + sensor.protocol_cfg["ip"] + "/api/" + sensor.protocol_cfg["hueUser"] + "/sensors/" + sensor.protocol_cfg["id"]
        response = requests.get(url, timeout=3)
        if response.status_code == 200:
            sensor_data = response.json()
            return sensor_data.get("state", {}), sensor_data.get("config", {})
    except Exception as e:
        logging.debug(f"Error getting sensor state from Hue Bridge: {e}")
    return None, None


