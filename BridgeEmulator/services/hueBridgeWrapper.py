"""
Hue Bridge Wrapper Service

This service wraps around a real Philips Hue bridge, passing through all devices
including lights, switches, dimmers, buttons, and sensors.
"""

import json
import logManager
import configManager
import requests
import weakref
from threading import Thread
from time import sleep
from datetime import datetime, timezone
from HueObjects import Sensor, Device, Light
from functions.core import nextFreeId
from sensors.discover import addHueMotionSensor, addHueSwitch, addHueRotarySwitch, addHueSecureContactSensor
from lights.discover import addNewLight

logging = logManager.logger.get_logger(__name__)
bridgeConfig = configManager.bridgeConfig.yaml_config

# Cache for device IDs to bridge objects
device_cache = {}


def getHueBridgeObject(hue_id, resource_type):
    """Get a cached reference to a bridge object by its Hue bridge ID"""
    cache_key = f"{resource_type}_{hue_id}"
    if cache_key in device_cache:
        logging.debug(f"Cache Hit for Hue {resource_type} {hue_id}")
        return device_cache[cache_key]()
    
    # Search in appropriate bridge config section
    search_sections = {
        "lights": "lights",
        "sensors": "sensors",
        "devices": "device"
    }
    
    if resource_type in search_sections:
        for key, obj in bridgeConfig[search_sections[resource_type]].items():
            if (hasattr(obj, 'protocol') and obj.protocol == "hue" and 
                hasattr(obj, 'protocol_cfg') and obj.protocol_cfg.get("hue_id") == hue_id):
                device_cache[cache_key] = weakref.ref(obj)
                logging.debug(f"Cache Miss for Hue {resource_type} {hue_id}")
                return obj
    
    logging.debug(f"Hue {resource_type} {hue_id} not found")
    return None


def discoverHueBridgeDevices(credentials):
    """
    Discover all devices from a Philips Hue bridge including lights, sensors, and switches.
    
    Args:
        credentials: Dictionary with 'ip' and 'hueUser' keys
    """
    if "hueUser" not in credentials or len(credentials["hueUser"]) < 32:
        logging.warning("Invalid Hue bridge credentials")
        return
    
    base_url = f"http://{credentials['ip']}/api/{credentials['hueUser']}"
    
    try:
        # Discover lights
        _discoverHueLights(base_url, credentials)
        
        # Discover sensors (switches, dimmers, motion sensors, etc.)
        _discoverHueSensors(base_url, credentials)
        
        logging.info("Hue bridge device discovery completed")
        
    except Exception as e:
        logging.error(f"Error discovering Hue bridge devices: {e}")


def _discoverHueLights(base_url, credentials):
    """Discover lights from Hue bridge"""
    try:
        response = requests.get(f"{base_url}/lights", timeout=3)
        if response.status_code != 200:
            logging.warning(f"Failed to get lights from Hue bridge: {response.status_code}")
            return
        
        lights = response.json()
        logging.info(f"Found {len(lights)} lights on Hue bridge")
        
        for hue_light_id, light_data in lights.items():
            # Check if light already exists
            existing_light = getHueBridgeObject(hue_light_id, "lights")
            if existing_light:
                logging.debug(f"Light {light_data['name']} already exists")
                continue
            
            # Map Hue light type to modelid
            modelid = _mapLightTypeToModel(light_data.get("type", ""), light_data.get("modelid", ""))
            
            # Create protocol configuration
            protocol_cfg = {
                "ip": credentials["ip"],
                "hueUser": credentials["hueUser"],
                "hue_id": hue_light_id,
                "modelid": light_data.get("modelid", modelid),
                "uniqueid": light_data.get("uniqueid", "")
            }
            
            # Add the light
            logging.info(f"Adding Hue light: {light_data['name']} (type: {light_data.get('type', 'Unknown')})")
            addNewLight(modelid, light_data["name"], "hue", protocol_cfg)
            
    except Exception as e:
        logging.error(f"Error discovering Hue lights: {e}")


def _mapLightTypeToModel(light_type, original_modelid=""):
    """Map Hue light type to a model ID"""
    # If we have the original model ID, use it for better accuracy
    if original_modelid:
        return original_modelid
    
    # Otherwise, map based on type
    type_map = {
        "Extended color light": "LCT015",
        "Color light": "LLC010",
        "Color temperature light": "LTW001",
        "Dimmable light": "LWB010",
        "On/Off light": "LOM001",
        "On/Off plug-in unit": "LOM001",
    }
    
    return type_map.get(light_type, "LCT015")


def _discoverHueSensors(base_url, credentials):
    """Discover sensors from Hue bridge including switches, dimmers, and motion sensors"""
    try:
        response = requests.get(f"{base_url}/sensors", timeout=3)
        if response.status_code != 200:
            logging.warning(f"Failed to get sensors from Hue bridge: {response.status_code}")
            return
        
        sensors = response.json()
        logging.info(f"Found {len(sensors)} sensors on Hue bridge")
        
        # Group sensors by device (using uniqueid prefix)
        device_groups = _groupSensorsByDevice(sensors)
        
        for device_id, device_sensors in device_groups.items():
            _addHueDevice(device_sensors, credentials)
            
    except Exception as e:
        logging.error(f"Error discovering Hue sensors: {e}")


def _groupSensorsByDevice(sensors):
    """Group sensors by device based on uniqueid"""
    device_groups = {}
    
    for sensor_id, sensor_data in sensors.items():
        # Skip Daylight sensor and other system sensors
        if sensor_data.get("type") in ["Daylight", "CLIPGenericStatus"]:
            continue
        
        uniqueid = sensor_data.get("uniqueid", "")
        if not uniqueid:
            continue
        
        # Extract device identifier (everything before the last component)
        # Example: "00:17:88:01:02:00:af:28-02-fc00" -> "00:17:88:01:02:00:af:28"
        parts = uniqueid.rsplit("-", 2)
        device_id = parts[0] if parts else uniqueid
        
        if device_id not in device_groups:
            device_groups[device_id] = {}
        
        device_groups[device_id][sensor_id] = sensor_data
    
    return device_groups


def _addHueDevice(device_sensors, credentials):
    """Add a Hue device based on its sensors"""
    # Determine device type based on sensors present
    sensor_types = {s.get("type") for s in device_sensors.values()}
    
    # Get the first sensor for basic info
    first_sensor = next(iter(device_sensors.values()))
    modelid = first_sensor.get("modelid", "")
    device_name = first_sensor.get("name", "Unknown Device")
    
    logging.info(f"Processing Hue device: {device_name} (model: {modelid}, types: {sensor_types})")
    
    # Motion sensor (has ZLLPresence, ZLLLightLevel, ZLLTemperature)
    if "ZLLPresence" in sensor_types or "ZHAPresence" in sensor_types:
        _addHueMotionSensorDevice(device_sensors, credentials)
    
    # Contact sensor
    elif "ZLLContact" in sensor_types or "ZHAContact" in sensor_types:
        _addHueContactSensorDevice(device_sensors, credentials)
    
    # Switch/Dimmer (has ZLLSwitch, ZGPSwitch, etc.)
    elif "ZLLSwitch" in sensor_types or "ZGPSwitch" in sensor_types:
        _addHueSwitchDevice(device_sensors, credentials)
    
    # Rotary switch (has ZLLRelativeRotary)
    elif "ZLLRelativeRotary" in sensor_types:
        _addHueRotarySwitchDevice(device_sensors, credentials)
    
    else:
        logging.debug(f"Unknown Hue device type with sensors: {sensor_types}")


def _addHueMotionSensorDevice(device_sensors, credentials):
    """Add a Hue motion sensor device"""
    # Check if already exists
    first_sensor = next(iter(device_sensors.values()))
    hue_sensor_id = next(iter(device_sensors.keys()))
    
    existing = getHueBridgeObject(hue_sensor_id, "sensors")
    if existing:
        logging.debug(f"Motion sensor {first_sensor.get('name')} already exists")
        return
    
    protocol_cfg = {
        "ip": credentials["ip"],
        "hueUser": credentials["hueUser"],
        "modelid": first_sensor.get("modelid", "SML001"),
        "hue_sensors": {hue_id: sensor.get("type") for hue_id, sensor in device_sensors.items()}
    }
    
    device_name = first_sensor.get("name", "Motion Sensor").replace("Hue motion ", "").replace("Hue ambient light ", "").replace("Hue temperature ", "")
    logging.info(f"Adding Hue motion sensor: {device_name}")
    addHueMotionSensor(device_name, "hue", protocol_cfg)


def _addHueContactSensorDevice(device_sensors, credentials):
    """Add a Hue contact sensor device"""
    first_sensor = next(iter(device_sensors.values()))
    hue_sensor_id = next(iter(device_sensors.keys()))
    
    existing = getHueBridgeObject(hue_sensor_id, "sensors")
    if existing:
        logging.debug(f"Contact sensor {first_sensor.get('name')} already exists")
        return
    
    protocol_cfg = {
        "ip": credentials["ip"],
        "hueUser": credentials["hueUser"],
        "modelid": first_sensor.get("modelid", "SOC001"),
        "hue_sensors": {hue_id: sensor.get("type") for hue_id, sensor in device_sensors.items()}
    }
    
    device_name = first_sensor.get("name", "Contact Sensor").replace("Hue contact ", "")
    logging.info(f"Adding Hue contact sensor: {device_name}")
    addHueSecureContactSensor(device_name, "hue", protocol_cfg)


def _addHueSwitchDevice(device_sensors, credentials):
    """Add a Hue switch/dimmer device"""
    first_sensor = next(iter(device_sensors.values()))
    hue_sensor_id = next(iter(device_sensors.keys()))
    modelid = first_sensor.get("modelid", "RWL021")
    
    existing = getHueBridgeObject(hue_sensor_id, "sensors")
    if existing:
        logging.debug(f"Switch {first_sensor.get('name')} already exists")
        return
    
    # Create sensor in bridgeConfig
    new_sensor_id = nextFreeId(bridgeConfig, "sensors")
    uniqueid = first_sensor.get("uniqueid", "")
    sensor_type = first_sensor.get("type", "ZLLSwitch")
    
    protocol_cfg = {
        "ip": credentials["ip"],
        "hueUser": credentials["hueUser"],
        "hue_id": hue_sensor_id,
        "modelid": modelid
    }
    
    deviceData = {
        "id_v1": new_sensor_id,
        "state": first_sensor.get("state", {"buttonevent": 0, "lastupdated": "none"}),
        "config": first_sensor.get("config", {"on": True, "battery": 100, "reachable": True}),
        "name": first_sensor.get("name", "Dimmer Switch"),
        "type": sensor_type,
        "modelid": modelid,
        "manufacturername": first_sensor.get("manufacturername", "Philips"),
        "swversion": first_sensor.get("swversion", ""),
        "uniqueid": uniqueid,
        "protocol": "hue",
        "protocol_cfg": protocol_cfg
    }
    
    logging.info(f"Adding Hue switch: {deviceData['name']} (model: {modelid})")
    bridgeConfig["sensors"][new_sensor_id] = Sensor.Sensor(deviceData)
    
    newDeviceObj = Device.Device(deviceData)
    newDeviceObj.add_element(deviceData["type"], bridgeConfig["sensors"][new_sensor_id])
    bridgeConfig["device"][newDeviceObj.id_v2] = newDeviceObj


def _addHueRotarySwitchDevice(device_sensors, credentials):
    """Add a Hue rotary switch device (e.g., Tap Dial)"""
    first_sensor = next(iter(device_sensors.values()))
    hue_sensor_id = next(iter(device_sensors.keys()))
    
    existing = getHueBridgeObject(hue_sensor_id, "sensors")
    if existing:
        logging.debug(f"Rotary switch {first_sensor.get('name')} already exists")
        return
    
    protocol_cfg = {
        "ip": credentials["ip"],
        "hueUser": credentials["hueUser"],
        "modelid": first_sensor.get("modelid", "RDM002"),
        "hue_sensors": {hue_id: sensor.get("type") for hue_id, sensor in device_sensors.items()}
    }
    
    device_name = first_sensor.get("name", "Tap Dial Switch")
    logging.info(f"Adding Hue rotary switch: {device_name}")
    addHueRotarySwitch(protocol_cfg)


def pollHueBridgeStates():
    """
    Continuously poll Hue bridge for state updates of all devices.
    This runs in a separate thread.
    """
    logging.info("Starting Hue bridge state polling service")
    
    # Get Hue bridge configuration
    hue_bridges = []
    if "hueBridges" in bridgeConfig["config"]:
        hue_bridges = bridgeConfig["config"]["hueBridges"]
    
    while True:
        try:
            for bridge in hue_bridges:
                if not bridge.get("enabled", False):
                    continue
                
                _pollBridgeLights(bridge)
                _pollBridgeSensors(bridge)
            
            sleep(1)  # Poll every second
            
        except Exception as e:
            logging.error(f"Error in Hue bridge polling: {e}")
            sleep(5)


def _pollBridgeLights(bridge):
    """Poll light states from a Hue bridge"""
    try:
        base_url = f"http://{bridge['ip']}/api/{bridge['hueUser']}"
        response = requests.get(f"{base_url}/lights", timeout=2)
        
        if response.status_code == 200:
            lights = response.json()
            for hue_light_id, light_data in lights.items():
                light_obj = getHueBridgeObject(hue_light_id, "lights")
                if light_obj and "state" in light_data:
                    # Update light state
                    light_obj.state.update(light_data["state"])
                    
    except Exception as e:
        logging.debug(f"Error polling lights from Hue bridge: {e}")


def _pollBridgeSensors(bridge):
    """Poll sensor states from a Hue bridge"""
    try:
        base_url = f"http://{bridge['ip']}/api/{bridge['hueUser']}"
        response = requests.get(f"{base_url}/sensors", timeout=2)
        
        if response.status_code == 200:
            sensors = response.json()
            for hue_sensor_id, sensor_data in sensors.items():
                sensor_obj = getHueBridgeObject(hue_sensor_id, "sensors")
                if sensor_obj:
                    # Update sensor state
                    if "state" in sensor_data:
                        sensor_obj.state.update(sensor_data["state"])
                    if "config" in sensor_data:
                        sensor_obj.config.update(sensor_data["config"])
                    
    except Exception as e:
        logging.debug(f"Error polling sensors from Hue bridge: {e}")


def startHueBridgeWrapper():
    """
    Start the Hue bridge wrapper service.
    Discovers devices and starts polling for state updates.
    """
    if "hueBridges" not in bridgeConfig["config"]:
        bridgeConfig["config"]["hueBridges"] = []
    
    # Discover devices from all configured bridges
    for bridge in bridgeConfig["config"]["hueBridges"]:
        if bridge.get("enabled", False):
            logging.info(f"Discovering devices from Hue bridge at {bridge['ip']}")
            discoverHueBridgeDevices(bridge)
    
    # Start polling thread
    if any(b.get("enabled", False) for b in bridgeConfig["config"]["hueBridges"]):
        Thread(target=pollHueBridgeStates, daemon=True).start()
    else:
        logging.info("No Hue bridges configured or enabled")
