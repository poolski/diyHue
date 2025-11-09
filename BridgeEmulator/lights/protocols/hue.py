import json
import logManager
import requests

logging = logManager.logger.get_logger(__name__)

def set_light(light, data):
    # Support both 'id' (legacy) and 'hue_id' (new) for compatibility
    hue_light_id = light.protocol_cfg.get("hue_id", light.protocol_cfg.get("id"))
    url = "http://" + light.protocol_cfg["ip"] + "/api/" + light.protocol_cfg["hueUser"] + "/lights/" + hue_light_id + "/state"
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
    # Support both 'id' (legacy) and 'hue_id' (new) for compatibility
    hue_light_id = light.protocol_cfg.get("hue_id", light.protocol_cfg.get("id"))
    state = requests.get("http://" + light.protocol_cfg["ip"] + "/api/" + light.protocol_cfg["hueUser"] + "/lights/" + hue_light_id, timeout=3)
    return state.json()["state"]

def discover(detectedLights, credentials):
    """
    Discover lights from a Hue bridge.
    Note: This is now primarily used for backward compatibility.
    The main discovery is handled by hueBridgeWrapper service.
    """
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
                    # Store hue_id instead of id for wrapper compatibility
                    detectedLights.append({"protocol": "hue", "name": light["name"], "modelid": modelid, "protocol_cfg": {"ip": credentials["ip"], "hueUser": credentials["hueUser"], "modelid": light["modelid"], "hue_id": id, "uniqueid": light["uniqueid"]}})
        except Exception as e:
            logging.info("Error connecting to Hue Bridge: %s", e)
