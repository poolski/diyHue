"""
Hue Bridge Wrapper Service

This service wraps around a real Philips Hue bridge, passing through all devices
including lights, switches, dimmers, buttons, and sensors.

Features:
- Automatic bridge discovery via SSDP/mDNS
- Interactive pairing for discovered bridges
- Manual configuration fallback
"""

import json
import logManager
import configManager
import requests
import weakref
import socket
import struct
import xml.etree.ElementTree as ET
from threading import Thread
from time import sleep
from datetime import datetime, timezone
from zeroconf import IPVersion, ServiceBrowser, ServiceStateChange, Zeroconf
from HueObjects import Sensor, Device, Light
from functions.core import nextFreeId
from sensors.discover import addHueMotionSensor, addHueSwitch, addHueRotarySwitch, addHueSecureContactSensor
from lights.discover import addNewLight

logging = logManager.logger.get_logger(__name__)
bridgeConfig = configManager.bridgeConfig.yaml_config

# Cache for device IDs to bridge objects
device_cache = {}

# Discovered bridges (not yet paired)
discovered_bridges = {}

# Pairing state for bridges awaiting link button press
pairing_bridges = {}


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


def discoverHueBridgesSSDP(timeout=5):
    """
    Discover Hue bridges on the network using SSDP.
    Returns a list of discovered bridge IPs.
    """
    SSDP_ADDR = '239.255.255.250'
    SSDP_PORT = 1900
    SSDP_MX = 3
    SSDP_ST = 'urn:schemas-upnp-org:device:basic:1'
    
    ssdpRequest = (
        'M-SEARCH * HTTP/1.1\r\n'
        f'HOST: {SSDP_ADDR}:{SSDP_PORT}\r\n'
        'MAN: "ssdp:discover"\r\n'
        f'MX: {SSDP_MX}\r\n'
        f'ST: {SSDP_ST}\r\n'
        '\r\n'
    )
    
    bridges = []
    
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(timeout)
        sock.sendto(ssdpRequest.encode('utf-8'), (SSDP_ADDR, SSDP_PORT))
        
        while True:
            try:
                data, addr = sock.recvfrom(1024)
                response = data.decode('utf-8')
                
                # Check if this is a Hue bridge response
                if 'IpBridge' in response or 'hue-bridgeid' in response:
                    # Extract IP from LOCATION header
                    for line in response.split('\r\n'):
                        if line.startswith('LOCATION:'):
                            location = line.split(':', 1)[1].strip()
                            # Extract IP from http://IP:PORT/...
                            ip = location.split('//')[1].split(':')[0]
                            if ip not in [b.get('ip') for b in bridges]:
                                # Get bridge info
                                bridge_info = _getBridgeInfo(ip)
                                if bridge_info:
                                    bridges.append(bridge_info)
                                    logging.info(f"Discovered Hue bridge via SSDP: {ip}")
            except socket.timeout:
                break
    except Exception as e:
        logging.debug(f"SSDP discovery error: {e}")
    finally:
        sock.close()
    
    return bridges


def discoverHueBridgesMDNS(timeout=5):
    """
    Discover Hue bridges on the network using mDNS/Zeroconf.
    Returns a list of discovered bridge IPs.
    """
    bridges = []
    
    class HueBridgeListener:
        def __init__(self):
            self.bridges = []
        
        def add_service(self, zc, type_, name):
            info = zc.get_service_info(type_, name)
            if info:
                ip = socket.inet_ntoa(info.addresses[0])
                bridge_info = _getBridgeInfo(ip)
                if bridge_info and ip not in [b.get('ip') for b in self.bridges]:
                    self.bridges.append(bridge_info)
                    logging.info(f"Discovered Hue bridge via mDNS: {ip}")
        
        def remove_service(self, zc, type_, name):
            pass
        
        def update_service(self, zc, type_, name):
            pass
    
    try:
        zeroconf = Zeroconf(ip_version=IPVersion.V4Only)
        listener = HueBridgeListener()
        browser = ServiceBrowser(zeroconf, "_hue._tcp.local.", listener)
        sleep(timeout)
        bridges = listener.bridges
        zeroconf.close()
    except Exception as e:
        logging.debug(f"mDNS discovery error: {e}")
    
    return bridges


def _getBridgeInfo(ip):
    """
    Get bridge information from description.xml
    Returns dict with bridge details or None
    """
    try:
        response = requests.get(f"http://{ip}/description.xml", timeout=2)
        if response.status_code == 200:
            root = ET.fromstring(response.content)
            
            # Extract bridge ID from XML
            ns = {'d': 'urn:schemas-upnp-org:device-1-0'}
            serial_number = root.find('.//d:serialNumber', ns)
            model_name = root.find('.//d:modelName', ns)
            
            if serial_number is not None and 'Philips hue' in (model_name.text if model_name is not None else ''):
                bridge_id = serial_number.text
                return {
                    'ip': ip,
                    'id': bridge_id,
                    'name': f"Hue Bridge ({bridge_id[-6:]})",
                    'paired': False
                }
    except Exception as e:
        logging.debug(f"Error getting bridge info from {ip}: {e}")
    
    return None


def autoDiscoverBridges():
    """
    Automatically discover Hue bridges using both SSDP and mDNS.
    Returns combined list of unique bridges.
    """
    logging.info("Starting automatic Hue bridge discovery...")
    
    # Try both discovery methods
    ssdp_bridges = discoverHueBridgesSSDP(timeout=3)
    mdns_bridges = discoverHueBridgesMDNS(timeout=3)
    
    # Combine and deduplicate
    all_bridges = ssdp_bridges + mdns_bridges
    unique_bridges = []
    seen_ips = set()
    
    for bridge in all_bridges:
        if bridge['ip'] not in seen_ips:
            seen_ips.add(bridge['ip'])
            unique_bridges.append(bridge)
    
    # Check which bridges are already configured
    if "hueBridges" in bridgeConfig["config"]:
        configured_ips = {b.get('ip') for b in bridgeConfig["config"]["hueBridges"]}
        for bridge in unique_bridges:
            bridge['paired'] = bridge['ip'] in configured_ips
    
    # Store discovered bridges
    for bridge in unique_bridges:
        if not bridge['paired']:
            discovered_bridges[bridge['ip']] = bridge
            logging.info(f"Found unpaired bridge: {bridge['name']} at {bridge['ip']}")
    
    logging.info(f"Discovery complete: {len(unique_bridges)} bridge(s) found")
    return unique_bridges


def pairWithBridge(ip, devicetype="diyhue#wrapper"):
    """
    Attempt to pair with a Hue bridge.
    Returns API key on success, or error message.
    
    Security: IP address is validated to prevent SSRF attacks.
    Only private network IPs are allowed (192.168.x.x, 10.x.x.x, 172.16-31.x.x).
    Loopback and public IPs are rejected.
    """
    # Validate IP address to prevent SSRF
    import ipaddress
    try:
        ip_obj = ipaddress.ip_address(ip)
        # Reject loopback addresses (127.0.0.1, ::1)
        if ip_obj.is_loopback:
            return {"success": False, "error": "Loopback addresses not allowed"}
        # Only allow private network IPs (typical for Hue bridges on local network)
        # This prevents SSRF attacks to external services
        if not ip_obj.is_private:
            return {"success": False, "error": "Only private network addresses allowed"}
    except ValueError:
        return {"success": False, "error": "Invalid IP address format"}
    
    # IP is validated - safe to make request to local network device
    try:
        response = requests.post(
            f"http://{ip}/api",
            json={"devicetype": devicetype},
            timeout=5
        )
        
        if response.status_code == 200:
            result = response.json()
            if isinstance(result, list) and len(result) > 0:
                if "success" in result[0]:
                    username = result[0]["success"]["username"]
                    logging.info(f"Successfully paired with bridge at {ip}")
                    
                    # Save to config
                    if "hueBridges" not in bridgeConfig["config"]:
                        bridgeConfig["config"]["hueBridges"] = []
                    
                    # Check if bridge already exists in config
                    existing = False
                    for bridge in bridgeConfig["config"]["hueBridges"]:
                        if bridge.get("ip") == ip:
                            bridge["hueUser"] = username
                            bridge["enabled"] = True
                            existing = True
                            break
                    
                    if not existing:
                        bridgeConfig["config"]["hueBridges"].append({
                            "ip": ip,
                            "hueUser": username,
                            "enabled": True
                        })
                    
                    # Save config
                    configManager.bridgeConfig.save_config()
                    
                    # Remove from discovered (unpaired) list
                    if ip in discovered_bridges:
                        del discovered_bridges[ip]
                    
                    return {"success": True, "username": username}
                    
                elif "error" in result[0]:
                    error = result[0]["error"]
                    return {"success": False, "error": error.get("description", "Unknown error")}
        
        return {"success": False, "error": "Invalid response from bridge"}
        
    except Exception as e:
        logging.error(f"Error pairing with bridge at {ip}: {e}")
        return {"success": False, "error": str(e)}


def getDiscoveredBridges():
    """
    Get list of discovered but unpaired bridges.
    """
    return list(discovered_bridges.values())


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
    Auto-discovers bridges, discovers devices, and starts polling for state updates.
    """
    if "hueBridges" not in bridgeConfig["config"]:
        bridgeConfig["config"]["hueBridges"] = []
    
    # Auto-discover bridges on the network
    discovered = autoDiscoverBridges()
    
    if discovered:
        unpaired = [b for b in discovered if not b['paired']]
        if unpaired:
            logging.info(f"Found {len(unpaired)} unpaired Hue bridge(s). Use the pairing API to connect.")
            logging.info("POST to /api with bridge IP to initiate pairing (requires link button press)")
    
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
