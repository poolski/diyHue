# Hue Bridge Wrapper

## Overview

DIYHue now includes a comprehensive wrapper around Philips Hue bridges, allowing it to pass through all devices from a real Hue bridge including lights, switches, dimmers, buttons, and sensors. This enables DIYHue to act as a unified gateway that combines devices from multiple sources:

- **Philips Hue Bridge** - All native Hue devices
- **Zigbee2MQTT (Z2M)** - Zigbee devices via MQTT
- **Other protocols** - deconz, Home Assistant, Tradfri, etc.

## Features

### Hue Bridge Passthrough
- ✓ Discovers all lights from connected Hue bridges
- ✓ Discovers all sensors (motion, temperature, light level, contact)
- ✓ Discovers all switches and dimmers (Hue dimmer switch, Tap switch, Tap Dial)
- ✓ Discovers all buttons
- ✓ Real-time state synchronization via polling
- ✓ Bidirectional control (changes made on DIYHue are sent to Hue bridge)

### Enhanced Z2M Support
Added comprehensive mapping for popular Zigbee switches and dimmers:

**Philips Hue Devices:**
- RWL020, RWL021, RWL022 (Hue Dimmer Switch)
- RDM002 (Hue Tap Dial Switch)
- ZGPSWITCH (Tap Switch)

**IKEA Devices:**
- E1524/E1810 (TRADFRI Remote Control)
- E1743 (TRADFRI On/Off Switch)
- E1744 (TRADFRI Wireless Dimmer / Symfonisk Sound Controller)

**Xiaomi/Aqara Devices:**
- WXKG01LM (MiJia Wireless Switch)
- WXKG11LM (Aqara Wireless Switch)
- WXKG12LM (Aqara Wireless Switch with Gyroscope)
- WXKG02LM (Aqara Double Key Wall Switch)
- WXKG03LM (Aqara Single Key Wall Switch)
- WXKG06LM (Aqara D1 Wireless Switch - Single)
- WXKG07LM (Aqara D1 Wireless Switch - Double)

**Other Devices:**
- 067773 (Legrand Wireless Switch)
- Remote Control N2
- PTM 215Z (EnOcean Switch)

### V2 API Enhancements
- ✓ Complete resource coverage including contact and tamper sensors
- ✓ All sensor types accessible via V2 API endpoints
- ✓ Proper resource structure matching latest Hue API specification

## Configuration

### Hue Bridge Configuration

Add Hue bridge(s) to your DIYHue configuration:

```yaml
config:
  hueBridges:
    - ip: "192.168.1.100"
      hueUser: "your-hue-api-key-here"
      enabled: true
    - ip: "192.168.1.101"
      hueUser: "another-hue-api-key"
      enabled: false
```

### Getting a Hue API Key

To get an API key from your Hue bridge:

1. Press the link button on your Hue bridge
2. Within 30 seconds, make a POST request:
   ```bash
   curl -X POST http://YOUR_BRIDGE_IP/api \
     -H "Content-Type: application/json" \
     -d '{"devicetype":"diyhue#wrapper"}'
   ```
3. The response will include your username (API key):
   ```json
   [{"success":{"username":"long-api-key-string-here"}}]
   ```
4. Use this username as the `hueUser` value in your configuration

## Device Discovery

### Automatic Discovery

When DIYHue starts with the wrapper enabled:

1. **Hue Bridge Discovery**: The wrapper queries all configured Hue bridges for devices
2. **Device Grouping**: Sensors are grouped by device based on their uniqueid
3. **Z2M Discovery**: Devices are discovered via MQTT topics

### State Synchronization

The wrapper runs a continuous polling service that updates device states every second.

## API Usage

All discovered devices are accessible via both V1 and V2 APIs.

### V2 API Endpoints

```http
GET /clip/v2/resource/device
GET /clip/v2/resource/light
GET /clip/v2/resource/button
GET /clip/v2/resource/motion
GET /clip/v2/resource/temperature
GET /clip/v2/resource/contact
GET /clip/v2/resource/tamper
```

## Button Event Mapping

Z2M switch actions are mapped to Hue button events:

| Action Type | Hue Event | Description |
|------------|-----------|-------------|
| press | X000 | Button pressed |
| hold | X001 | Button held |
| release | X002 | Short press released |
| hold_release | X003 | Long press released |

Where X is the button number (1-4).

## Troubleshooting

Check logs with: `tail -f diyhue.log`

For detailed documentation, see the full wrapper documentation in this directory.
