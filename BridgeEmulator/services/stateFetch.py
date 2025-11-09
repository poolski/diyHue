import logManager
import configManager
from lights.protocols import protocols, hue
from time import sleep
from datetime import datetime, timedelta, timezone
from functions.rules import rulesProcessor
from functions.behavior_instance import checkBehaviorInstances

logging = logManager.logger.get_logger(__name__)
bridgeConfig = configManager.bridgeConfig.yaml_config

def syncWithLights(off_if_unreachable): #update Hue Bridge lights states
    while True:
        logging.info("start lights sync")
        for key, light in bridgeConfig["lights"].items():
            protocol_name = light.protocol
            for protocol in protocols:
                if "lights.protocols." + protocol_name == protocol.__name__ and protocol_name not in ["mqtt", "flex", "mi_box", "dummy"]:
                    try:
                        logging.debug("fetch " + light.name)
                        newState = protocol.get_light_state(light)
                        logging.debug(newState)
                        light.state.update(newState)
                        light.state["reachable"] = True
                    except Exception as e:
                        light.state["reachable"] = False
                        if off_if_unreachable:
                            light.state["on"] = False
                        logging.warning(light.name + " is unreachable: %s", e)

        sleep(10) #wait at last 10 seconds before next sync
        i = 0
        while i < 300: #sync with lights every 300 seconds or instant if one user is connected
            for key, user in bridgeConfig["apiUsers"].items():
                lu = user.last_use_date
                try: #in case if last use is not a proper datetime
                    lu = datetime.strptime(lu, "%Y-%m-%dT%H:%M:%S")
                    if abs(datetime.now(timezone.utc).replace(tzinfo=None) - lu) <= timedelta(seconds = 2):
                        i = 300
                        break
                except Exception as e:
                    logging.warning(user.last_use_date + " is not: %s", e)
                    logging.warning(e)
            i += 1
            sleep(1)

def syncWithSensors(): #update sensor states from upstream Hue Bridge
    """Poll sensors (switches, buttons, etc.) from upstream Hue Bridge and trigger rules/behaviors"""
    while True:
        logging.info("start sensors sync")
        current_time = datetime.now()
        for key, sensor in bridgeConfig["sensors"].items():
            if sensor.protocol == "hue":
                try:
                    logging.debug("fetch sensor " + sensor.name)
                    newState, newConfig = hue.get_sensor_state(sensor)
                    if newState is not None:
                        # Check if state changed to trigger rules
                        state_changed = False
                        for state_key in newState.keys():
                            if state_key in sensor.state and sensor.state[state_key] != newState[state_key]:
                                state_changed = True
                                sensor.dxState[state_key] = current_time
                        
                        sensor.state.update(newState)
                        if newConfig:
                            sensor.config.update(newConfig)
                        
                        # Trigger rules and behavior instances if state changed
                        if state_changed:
                            logging.debug(f"Sensor {sensor.name} state changed, triggering rules")
                            rulesProcessor(sensor, current_time)
                            checkBehaviorInstances(sensor)
                except Exception as e:
                    logging.warning(f"Error syncing sensor {sensor.name}: {e}")

        sleep(2) #poll sensors more frequently than lights (every 2 seconds)

