from typing import List, Dict


class Location:
    def __init__(self, latitude: float, longitude: float):
        self.latitude: float = latitude
        self.longitude: float = longitude


class Building:
    def __init__(self, address: str, solar_arrays: List[Dict]):
        self.address: str = address
        self.solar_arrays = solar_arrays

        # todo: work out the location of the building with ethe
        self.location: Location = None