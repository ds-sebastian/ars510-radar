# Home Assistant bridge

Your RAV4 in Home Assistant: doors, lock, gear, speed, odometer, lights, cruise, blind spot, the pre-collision
system and the radar's lead, plus the comma device's 12 V reading, ignition, openpilot state and GPS location.

A small process on the comma device reads openpilot's CAN stream, decodes the Toyota body messages (from opendbc's
Toyota DBCs) and the radar's car-bus messages (decoded in [docs/13](../docs/13_car_bus_messages.md)), and publishes
them to your MQTT broker with Home Assistant's
[MQTT discovery](https://www.home-assistant.io/integrations/mqtt/#mqtt-discovery). The entities show up on their own
under one device, **RAV4**; nothing is installed in Home Assistant beyond the MQTT integration. The bridge only
reads: it sends nothing on the car's CAN buses and leaves openpilot's files untouched.

```
car CAN ──> panda ──> openpilot `can`, pandaStates, deviceState, GPS ──> ha_bridge.py ──MQTT──> broker ──> Home Assistant
```

**Why the comma device.** On the TSS2 RAV4 the OBD port sits behind the gateway and carries no broadcast traffic, so a
dongle there sees nothing without polling. The comma harness at the camera sees the car bus (bus 0) and the radar bus
(bus 1), and the device already has Wi-Fi, LTE and GPS.

## Setup

1. **Broker.** In Home Assistant, install the Mosquitto broker add-on (or use any MQTT broker), add the MQTT
   integration, and create a user for the car (Settings → People → Users, or the add-on's `logins`).
2. **On the comma device** (SSH), with this repo cloned to `/data/ars510-radar` as for the radar install, write
   `/data/ars510_ha.json`:

   ```json
   {"host": "homeassistant.local", "port": 1883, "username": "rav4", "password": "…"}
   ```

   Optional keys: `"tls": true` (port 8883), `"name"` (device name, default `RAV4`), `"node_id"` (MQTT id, default
   `rav4`), `"discovery_prefix"` (default `homeassistant`), `"location": false` (no GPS). If the device cannot resolve
   `homeassistant.local`, use the broker's address.
3. **Try it:** `PYTHONPATH=/data/openpilot python /data/ars510-radar/home_assistant/ha_bridge.py`. The log prints
   `mqtt: connected to …` and the RAV4 device appears in Home Assistant under Settings → Devices → MQTT.
4. **Start it on every boot:** `python /data/ars510-radar/home_assistant/ha_bridge.py --install-autostart` adds one
   marked line to `/data/continue.sh` (AGNOS's boot script, outside `/data/openpilot`, so fork updates keep it) that
   runs [`start.sh`](start.sh) in the background; it logs to `/tmp/ars510_ha.log`. `--remove-autostart` takes it out
   again.

**Off the home network.** The device publishes whenever it can reach the broker: on home Wi-Fi when you park, or
everywhere over LTE if the broker is reachable from there (for example over Tailscale, or a broker with TLS). While it
cannot, it keeps retrying every 2-60 s and sends the current state on reconnect.

**After you park.** openpilot keeps the device on for a while after the ignition goes off, then shuts it down. All
states are retained by the broker, and the data entities have no availability topic, so Home Assistant keeps the last
values (location, odometer, doors, lock) while the car sleeps. **Comma device** goes offline about 90 s after the device
stops (the MQTT last will) and says whether the other values are live. Locking or opening the car while the device is
off is not seen.

## Entities

Status: ● read by openpilot on the RAV4 TSS2 2023, or decoded on this car in [docs/13](../docs/13_car_bus_messages.md);
◐ defined in opendbc's Toyota DBCs, not yet checked on this car's bus (run the [coverage check](#check-your-car) on one
of your drives). An entity appears in Home Assistant the first time its message is seen, so a message your car does
not send leaves no dead entity.

| entity | key | type | source | |
|---|---|---|---|---|
| Front left / front right / rear left / rear right door | `door_fl` `door_fr` `door_rl` `door_rr` | binary, door | `BODY_CONTROL_STATE` 0x620 | ● |
| Driver seatbelt unlatched | `seatbelt_driver_unlatched` | binary | 0x620 | ● |
| Parking brake | `parking_brake` | binary | 0x620 | ● |
| Door lock | `unlocked` | binary, lock (on = unlocked) | `DOOR_LOCKS` 0x638 `LOCK_STATUS` | ◐ |
| Odometer | `odometer_km` | km, total increasing (converted from miles when the car shows miles) | `UI_SETTING` 0x611 | ◐ |
| Gear | `gear` | P / R / N / D / B / S | `GEAR_PACKET` 0x3BC, hybrid `GEAR_PACKET_HYBRID` 0x127 | ● |
| Speed | `speed_kph` | km/h, every 5 s at most | `SPEED` 0xB4 | ● |
| Turn signal | `turn_signal` | off / left / right | `BLINKERS_STATE` 0x614 | ● |
| Hazard lights | `hazard_light` | binary | 0x614 | ◐ |
| Low beams, high beams | `low_beam` `high_beam` | binary, light | `LIGHT_STALK` 0x622 | ◐ |
| Automatic high beams | `auto_high_beam` | binary (diagnostic) | 0x622 | ● |
| Cruise control, cruise engaged | `cruise_main_on` `cruise_active` | binary | `PCM_CRUISE_2` 0x1D3, `PCM_CRUISE` 0x1D2 | ● |
| Cruise set speed | `cruise_set_speed_kph` | km/h, unknown with cruise off | 0x1D3 `SET_SPEED` | ● |
| Brake hold | `brake_hold_active` | binary | `ESP_CONTROL` 0x3B7 | ● |
| Blind spot left / right | `blind_spot_l` `blind_spot_r` | binary, occupancy (adjacent or approaching) | `BSM` 0x3F6 | ◐ |
| Engine running, engine speed | `engine_running` `engine_rpm` | binary, rpm | `ENGINE_RPM` 0x1C4 | ◐ |
| Lead distance, lead relative speed | `lead_distance_m` `lead_rel_speed_kph` | m, km/h (negative closing), every 2 s at most; unknown without an ACC target | radar `DSU_CRUISE` 0x365 ([docs/13](../docs/13_car_bus_messages.md#0x365-lead-distance-and-relative-speed-)) | ● |
| Pre-collision system | `pcs_state` | on / off / faulted | radar `PCS_HUD` 0x411 `PCS_INDICATOR` | ● |
| Pre-collision sensitivity | `pcs_sensitivity` | off / high / mid / low (diagnostic) | 0x411 | ● |
| Radar blocked, radar temperature alert, radar beam alignment alert | `radar_blocked` `radar_temperature` `radar_beam_adjust` | binary, problem | 0x411 `PCS_DUST2` / `PCS_TEMP2` / `FRD_ADJ` | ◐ |
| Pre-collision braking | `pcs_braking_available` | binary: the radar's PCS / AEB request (0x344) reaches the car | presence of 0x344 ([docs/13](../docs/13_car_bus_messages.md#openpilot-longitudinal-filter-or-disable)) | ● |
| Safety event | `safety_event` | event: `forward_collision_warning`, `pcs_alarm`, `emergency_braking` | 0x411 `FCW`, 0x344 `PCSALM`, 0x283 `STATE` 3 ([docs/15](../docs/15_aeb_pcs.md)) | ● / ● / ◐ |
| Radar CAN filter | `radar_filter` | binary (diagnostic): a smartDSU-style filter's 0x2FF heartbeat | presence of 0x2FF | ● |
| Radar object list | `radar_object_list` | binary (diagnostic): the radar bus is running | presence of 0x80 on bus 1 | ● |
| 12 V battery | `battery_voltage` | V, every 30 s at most | `pandaStates` voltage | ● |
| Ignition | `ignition` | binary, power | `pandaStates` | ● |
| openpilot engaged | `engaged` | binary | `selfdriveState` (`controlsState` on older forks) | ● |
| Location | `location` | device tracker (GPS), every 10 s at most | `gpsLocationExternal` / `gpsLocation` | ● |
| Comma device temperature, free space | `device_temp` `free_space` | °C, % (diagnostic) | `deviceState` | ● |
| Comma device | `online` | connectivity (MQTT last will) | the bridge | ● |

The presence entities (pre-collision braking, radar CAN filter, radar object list) read unknown while the car bus
sleeps and for their first 2 s awake, so a start-up never reads as "off". **Pre-collision braking** off with the car
running means the radar's PCS / AEB request does not reach the car, which is what openpilot's radar disable (alpha
longitudinal) does ([docs/13](../docs/13_car_bus_messages.md#openpilot-longitudinal-filter-or-disable)); with a radar
CAN filter or stock longitudinal it stays on. The radar's values (lead, pre-collision system) read unknown once the
radar stops sending them.

Topics: discovery under `homeassistant/<component>/rav4/<key>/config`, states under `ars510_ha/rav4/<key>`, all
retained; `ars510_ha/rav4/status` is `online` / `offline`; safety events go to `ars510_ha/rav4/safety_event`
(not retained).

### Automation ideas

- notify when a door is open or the car is unlocked after the device went offline at home;
- notify on any **Safety event**, or when **Pre-collision braking** turns off while **Ignition** is on;
- warn when **12 V battery** drops below about 12.0 V with the ignition off;
- a "where did I park" card from **Location**, and the odometer for service reminders.

## Check your car

Run a drive's log through the bridge on a computer with openpilot (for its `LogReader`), without a broker:

```bash
python home_assistant/ha_bridge.py --config "" --replay <rlog or qlog> --dry-run > ha_messages.txt
```

It prints every MQTT message the drive would have produced, and on stderr how many frames of each message the
log carries. A ◐ message with frames and sensible values (for example the lock flipping when you lock the car) can
move to ●; one with no frames is not sent on your car's bus. A CAN CSV in the
[`data/sample`](../data/sample) format (`t_s,bus,address,data_hex`) works as well.

## Files

| file | what |
|---|---|
| [`ha_bridge.py`](ha_bridge.py) | entry point and options (`--help`) |
| [`start.sh`](start.sh) | boot launcher used by `--install-autostart` (openpilot's Python and `PYTHONPATH`) |
| [`ars510_ha/signals.py`](ars510_ha/signals.py) | the signals: start bit, length, byte order, scale and offset as in opendbc, and DBC bit extraction |
| [`ars510_ha/car.py`](ars510_ha/car.py) | frames to values: enums, unit conversion, presence, staleness, safety events |
| [`ars510_ha/entities.py`](ars510_ha/entities.py) | the Home Assistant entities and their discovery payloads |
| [`ars510_ha/mqtt.py`](ars510_ha/mqtt.py) | a publish-only MQTT 3.1.1 client on the standard library (openpilot's Python has no MQTT package) |
| [`ars510_ha/bridge.py`](ars510_ha/bridge.py) | change detection and rate limits, reconnects, the device loop, replay, autostart |

Tests: [`tests/test_home_assistant.py`](../tests/test_home_assistant.py). The signal table matches opendbc's DBCs bit
for bit: 37 signals, 500 random frames each, decoded with cantools against `opendbc/dbc/generator/toyota`.
