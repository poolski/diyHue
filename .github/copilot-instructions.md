# AI Coding Agent Instructions for diyHue

Welcome to the diyHue repository! This document provides essential guidance for AI coding agents to be productive in this codebase. Follow these instructions to understand the architecture, workflows, and conventions of the project.

## Project Overview

diyHue is an open-source Hue Bridge emulator written in Python. It integrates various smart home solutions, enabling users to control lights and sensors without vendor-specific hardware. Key features include:
- Support for multiple light protocols (e.g., ZigBee, MQTT, WS2812B).
- Integration with apps like Hue Essentials and Home Assistant.
- No cloud dependency by design.

### Key Components
- **BridgeEmulator/**: Core logic for emulating the Hue Bridge.
  - `HueEmulator3.py`: Main entry point for the emulator.
  - `services/`: Handles communication with external systems (e.g., MQTT, Deconz).
  - `functions/`: Utility modules for behaviors, rules, and network operations.
- **flaskUI/**: Web interface for managing the emulator.
  - `core/`, `devices/`, `error_pages/`: Flask views and templates.
  - `templates/`: HTML templates for the web UI.
- **HueObjects/**: Abstractions for Hue entities (e.g., lights, sensors, rules).
- **lights/**: Protocol-specific implementations for controlling lights.
- **RemoteApi/**: Handles remote API integration with Hue Essentials.

## Developer Workflows

### Setting Up the Environment
1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
2. Ensure `coap-client` and `faketime` are installed (e.g., `apt install libcoap2-bin faketime`).

### Running the Emulator
- Start the emulator:
  ```bash
  python BridgeEmulator/HueEmulator3.py
  ```
- Enable debug mode for detailed logs:
  ```bash
  python BridgeEmulator/HueEmulator3.py --debug true
  ```

### Testing
- Use the `Hue Essentials` app to test light control and remote API functionality.
- For remote API testing, disable WiFi on your phone and verify connectivity.

### Debugging
- Logs are critical for debugging. Enable debug mode and inspect logs for issues.
- Key log files and debug points:
  - `BridgeEmulator/logManager/logger.py`
  - `RemoteApi/remoteApiServer.py`

## Project-Specific Conventions

### Code Structure
- Follow the modular structure: separate core logic, services, and UI components.
- Use `functions/` for reusable utilities (e.g., `rulesProcessor` in `functions/rules.py`).

### Naming Conventions
- Use descriptive names for modules and functions (e.g., `configHandler.py`, `runtimeConfigHandler.py`).
- Follow Python PEP-8 guidelines for code style.

### Integration Points
- **MQTT**: Managed in `services/mqtt.py`.
- **Deconz**: ZigBee integration in `services/deconz.py`.
- **Remote API**: Implements Hue Essentials integration in `RemoteApi/`.
- **Web UI**: Flask-based interface in `flaskUI/`.

## External Dependencies
- Python packages: `ws4py`, `requests`, `astral`, `paho-mqtt`.
- System tools: `coap-client`, `faketime`.
- Node.js for UI development (see `flaskUI/README.md`).

## Examples and Patterns

### Adding a New Light Protocol
1. Create a new module in `lights/protocols/`.
2. Implement the required methods for discovery and control.
3. Register the protocol in `lights/discover.py`.

### Adding a New Service
1. Add the service logic in `services/`.
2. Update `HueEmulator3.py` to initialize the service.
3. Ensure the service follows the existing patterns (e.g., logging, error handling).

## Additional Resources
- [diyHue Documentation](https://diyhue.readthedocs.io/)
- [Slack Community](https://diyhue.slack.com/)
- [Discourse Forum](https://diyhue.discourse.group/)
- [Philips Hue V2 Python Client](https://github.com/FengChendian/python-hue-v2)

---

For any questions or clarifications, refer to the documentation or open an issue in the repository.