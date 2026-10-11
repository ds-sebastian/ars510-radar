# 15. Testing PCS / AEB safely: a runbook for testers

The radar's pre-collision system (PCS) is still decoded only up to its alarm stage ([13](13_car_bus_messages.md#a-recorded-stock-pcs-alarm-u3)).
The rest of what an AEB relay needs ([13](13_car_bus_messages.md#where-a-relay-stands-for-developers)) can only come from
recorded activations: the braking stages, whether a disabled radar still raises its bus-1 alarm flag, and what the dash
reacts to. This page describes how to record them without putting anyone at risk.

**Read this first.** Toyota's owner's manual tells owners not to test PCS themselves. The system does not promise to
warn or brake in every case. On every run **the driver stops the car**. Anything the car does on its own is a bonus to
record, never something to rely on. Stop the session after anything unexpected.

## 1. The target: soft, and visible to the radar

U3 showed that an inflatable decoration does not appear in the radar's object list at all: air-filled vinyl reflects
almost nothing at 77 GHz ([13](13_car_bus_messages.md#a-recorded-stock-pcs-alarm-u3)). The target has to be **harmless to
hit and radar-visible**.

- **Best: a commercial ADAS soft target.** An inflatable or foam "soft car" or pedestrian dummy made for AEB testing.
  Its skin is built to reflect radar like the real thing.
- **DIY: a light box with corner reflectors.** Cardboard or foam, roughly the size of a car's rear (about 1.5 × 1 m),
  with one or two **corner reflectors** inside. A corner reflector is three flat plates meeting at right angles, such as a
  cardboard corner lined with aluminium foil, opening towards the car. It returns a strong echo and is light enough to be
  pushed over without damage.
- **Never** a person, a parked car or anything heavy or rigid.
- **Check it before running at it.** Drive slowly towards the target with logging on (section 4). Confirm that it
  appears in the radar's object list or as its ACC target at 20-40 m (`tools/decode_log.py`, [09](09_tools_and_data.md)).
  If the radar does not list it, any warning comes from the camera, which is a different test (run B).

## 2. Place and people

- A **private, closed lot** with the owner's permission: no traffic, no pedestrians, no parked cars in the line of
  travel.
- A **long, clear run-out** past the target, so a late stop rolls into empty space.
- A **spotter outside the car** who keeps the area clear and calls each run. The driver only drives.
- Dry pavement, daylight. Repeat at dusk afterwards if you want night behaviour.

## 3. Speed and procedure

- **Speed.** Start at 10-15 km/h. Raise in steps of about 5 km/h only after a run behaved as expected, and stay below
  30 km/h. U3's alarm came at 25 km/h.
- **Each run.** Drive straight at the target, foot over the brake, and press the bookmark (flag) button at the start.
  Brake at a cone line placed well before the target, whether or not the car has done anything.
  - **Warning runs:** brake normally after the warning.
  - **Braking runs (run C only):** the cone line sits closer, so the car gets a chance to act first. Use only a target
    that is harmless to hit.
- Note each run: number, speed, target, what the dash showed or the car did, and the time.

## 4. Recording

- **Radar enabled:** stock ACC (openpilot lateral only) or openpilot longitudinal through a radar CAN filter. Run D is
  the exception.
- **Logging:** leave the comma device recording; its rlogs carry all three CAN buses (car, radar, camera side). Keep
  the qcamera files for your own review.
- **Before leaving the lot,** note the route and the segment of each run.

## 5. The runs and what each answers

| run | setup | answers |
|---|---|---|
| A | radar-visible soft car, 15-25 km/h, warning runs | the alarm and the radar-bus alarm flag (0x100) on a clean target |
| B | the decoration alone (a plain inflatable), warning runs | whether a warning can come from the camera alone |
| C | radar-visible soft car, braking runs | pre-fill, brake assist and autonomous braking: their car-bus frames and how the radar marks them on bus 1 |
| D | radar-visible soft car under alpha long (radar disabled), warning-run speeds, driver brakes as usual | whether a disabled radar still raises 0x100, which decides whether an AEB relay is possible at all |

In run D the car will not warn or brake: openpilot longitudinal has disabled the radar's car-bus output. The driver
brakes as on any normal approach.

## 6. Sharing

Open a [research finding](https://github.com/ds-sebastian/ars510-radar/issues/new/choose) with the run table and the
route and segment of each run. Offer the rlogs privately; they carry the VIN. The repo publishes signals only:
- no route or dongle IDs, VINs or GPS;
- no camera footage or stills, unless you say otherwise.
