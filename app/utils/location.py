import math


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return distance in km between two coordinates."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(dlon / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def bounding_box(lat: float, lon: float, radius_km: float):
    """Return (min_lat, max_lat, min_lon, max_lon) bounding box."""
    delta_lat = math.degrees(radius_km / 6371.0)
    delta_lon = math.degrees(radius_km / (6371.0 * math.cos(math.radians(lat))))
    return lat - delta_lat, lat + delta_lat, lon - delta_lon, lon + delta_lon
