from enum import Enum
from typing import List, Dict
from math_utils import centroid, Location


class SolarPanelArray:
    def __init__(self, location: Location, azimuth_degs: float, area_m2: float, energy_gen: float):
        self.location: Location = location
        self.azimuth_degs: float = azimuth_degs
        self.area_m2: float = area_m2
        self.energy_gen: float = energy_gen

    def to_dict(self):
        return {
            "location": self.location.to_dict(),
            "azimuth_degs": self.azimuth_degs,
            "area_m2": self.area_m2,
            "energy_gen": self.energy_gen
        }


class Building:
    def __init__(self, address_str: str, address: Dict[any, any], solar_arrays: List[SolarPanelArray]):
        self.address_str: str = address_str
        self.address: Dict[any, any] = address
        self.solar_arrays: List[SolarPanelArray] = solar_arrays

        # Derived state
        self.location: Location = centroid([array.location for array in solar_arrays])

        self.total_solar_area_m2: float = sum([array.area_m2 for array in solar_arrays])
        self.potential_savings_gbp: float = self._calc_potential_savings_gbp()


    def _calc_potential_savings_gbp(self):
        unit_rate_gbp_per_kwh = 0.28
        battery_usage_multiplier = 0.4 # In Half Day

        total_solar_energy_gen = sum([array.energy_gen for array in self.solar_arrays])

        return total_solar_energy_gen * battery_usage_multiplier * unit_rate_gbp_per_kwh


class AutoAuditError(Enum):
    AREA_UNDER_6M2 = 0
    AREA_OVER_40M2 = 1
    LOW_SAVING = 2