"""A minimal stand-in for opendbc.car, for tests that import the profile files without an opendbc checkout."""
import types


def fake_opendbc() -> dict:
  """Just enough of opendbc.car for a profile file to import: structs.RadarData and RadarInterfaceBase."""
  class Point:
    trackId, dRel, yRel, vRel = 0, 0.0, 0.0, 0.0

    def __init__(self, **fields):  # RadarPoint(trackId=..., ...) as with opendbc's capnp structs
      self.__dict__.update(fields)

  class Errors:
    radarUnavailableTemporary = canError = False

  class RadarData:
    RadarPoint = Point

    def __init__(self):
      self.points, self.errors = [], Errors()

  class RadarInterfaceBase:
    def __init__(self, CP):
      self.CP, self.frame = CP, 0

  car = types.ModuleType("opendbc.car")
  car.structs = types.SimpleNamespace(RadarData=RadarData)
  interfaces = types.ModuleType("opendbc.car.interfaces")
  interfaces.RadarInterfaceBase = RadarInterfaceBase
  return {"opendbc": types.ModuleType("opendbc"), "opendbc.car": car, "opendbc.car.interfaces": interfaces}
