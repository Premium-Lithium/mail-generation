from typing import List


class Location:
    def __init__(self, latitude: float, longitude: float):
        self.latitude: float = latitude
        self.longitude: float = longitude

    def to_dict(self):
        return {
            "latitude": self.latitude,
            "longitude": self.longitude
        }


def centroid(points: List[Location]) -> Location:
    if not points:
        return None

    lat_sum, lon_sum = 0, 0
    for loc in points:
        lat_sum += loc.latitude
        lon_sum += loc.longitude

    centroid_lat = lat_sum / len(points)
    centroid_lon = lon_sum / len(points)

    return Location(centroid_lat, centroid_lon)