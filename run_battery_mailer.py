import requests
import warnings
warnings.simplefilter(action='ignore', category=FutureWarning)

import sys
from urllib.parse import quote
import time
from supabase import create_client, Client
import math
from pyproj import Proj, transform

from PIL import Image, ImageDraw
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.chrome.service import Service as ChromeService
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.options import Options
import xml.etree.ElementTree as ET

from model import *
from math_utils import *


WIDTH = 1920
HEIGHT = 1080


def main():
    buildings: List[Building] = extract_buildings_from('region-5.kml')

    google_chrome = setup_headless_chrome_driver()

    for building in buildings:
        customer_id = create_new_database_record_for(building, google_chrome)
        # generate_flyer_for(customer_id)

    google_chrome.quit();


def create_new_database_record_for(building: Building, driver):
    google_earth_url = generate_google_earth_url_for(building.location)

    img_path = f"{building.address}.png"
    take_google_earth_screenshot(google_earth_url, img_path, driver)

    # todo: add production supabase url and key
    # url: str = os.environ.get("SUPABASE_URL")
    url: str = "http://localhost:54321"

    # key: str = os.environ.get("SUPABASE_KEY")
    key: str = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZS1kZW1vIiwicm9sZSI6ImFub24iLCJleHAiOjE5ODM4MTI5OTZ9.CRXP1A7WOeoJeXxjNni43kdQwgnWNReilDMblYTn_I0"

    supabase: Client = create_client(url, key)

    database_entry = {
        "address": building.address,
        "potential_savings_with_battery_gbp": building.potential_savings_gbp,
        "solar_array_info": [ array.to_dict() for array in building.solar_arrays ],
        "google_earth_url": google_earth_url
    }

    with open(img_path, "rb") as file:
        bucket_name = "existing-solar-property-screenshots"
        img_path_encoded = quote(img_path)
        data = supabase.storage.from_(bucket_name).upload(img_path_encoded, file)
        public_url = supabase.storage.from_(bucket_name).get_public_url(img_path_encoded)

        database_entry["screenshot_url"] = public_url

    audit_errors = catch_auto_audit_errors_on(building)
    if audit_errors:
        database_entry["audit_flags"] = audit_errors

    data, count = supabase.table('existing-solar-properties').insert(database_entry).execute()
    customer_uuid = data[1][0]["id"]

    return customer_uuid


def generate_google_earth_url_for(location: Location):
    distance = 2000
    verticalFoV_degs = 35
    heading = 0 # Facing due north

    # todo: determine tilt and lat offset from google earth coverage map API (0 if 2D, 45 if 3D)
    has_3d_map_view = False

    tilt = 45 if has_3d_map_view else 0
    lat_offset = 0.00016 if has_3d_map_view else 0

    url = f"https://earth.google.com/web/@{location.latitude + lat_offset},{location.longitude},{distance}d,{math.radians(verticalFoV_degs)}y,{heading}h,{tilt}t,0r"

    return url


# 
def catch_auto_audit_errors_on(building) -> AutoAuditError:
    errors = []

    if building.potential_savings_gbp < 120:
        errors.append(AutoAuditError.LOW_SAVING.value)

    if building.total_solar_area_m2 < 6:
        errors.append(AutoAuditError.AREA_UNDER_6M2.value)

    if building.total_solar_area_m2 > 40:
        errors.append(AutoAuditError.AREA_OVER_40M2.value)

    return errors


def generate_flyer_for(customer_id: str):
    url = 'http://localhost:3000/generate-postcard'  # Replace with your actual URL

    data = {
        "customerId": customer_id,
        "type": "existingSolar"
    }

    # todo: call our generate-postcard endpoint

    response = requests.post(url, json=data)

    print(response)
    if response.ok:
        print("Success:", response.json())
    else:
        print("Error:", response.status_code)


def extract_buildings_from(kml_file_path: Path):
    solar_arrays = extract_solar_array_data_from(kml_file_path)

    buildings_dict = {}

    for solar_array in solar_arrays:
        address = get_address_of(solar_array.location)

        if address not in buildings_dict:
            building_info = { "address": address, "arrays": [] }
            buildings_dict[address] = building_info

        buildings_dict[address]["arrays"].append(solar_array)

    print("Combinging arrays into buildings...")
    buildings = []
    for address, building_info in buildings_dict.items():
        buildings.append(Building(address, building_info["arrays"]))

    print(f"Created {len(buildings)} buildings...")

    return buildings


def get_address_of(location: Location):
    response = requests.post('http://localhost:3000/solar-proposals/geocoding', json={
        "lat": location.latitude, "lon": location.longitude
    })
    response = response.json()

    # todo: handle the case where the address look up fails

    return response['results'][0]['formatted_address']


def extract_solar_array_data_from(kml_file_path: Path) -> List[SolarPanelArray]:
    tree = ET.parse(kml_file_path)
    root = tree.getroot()

    # Define the namespaces (important for finding elements)
    namespaces = {
        '': "http://www.opengis.net/kml/2.2",
        'gx': "http://www.google.com/kml/ext/2.2"
    }

    # Iterate over all placemarks
    solar_arrays = []

    polygons = []
    for placemark in root.findall('.//{http://www.opengis.net/kml/2.2}Placemark', namespaces):
        polygon = placemark.find('.//{http://www.opengis.net/kml/2.2}Polygon', namespaces)

        if polygon is not None:
            polygons.append(polygon)

    total_arrays = len(polygons)
    print(f"Found {total_arrays} solar arrays in {kml_file_path}...")
    for idx, polygon in enumerate(polygons):
        array = create_solar_panel_array_from(polygon, namespaces)
        solar_arrays.append(array)

        print(f"\rGathering data on solar array {idx + 1}/{total_arrays}...", end="")
        sys.stdout.flush()

    print("\n")

    return solar_arrays


def setup_headless_chrome_driver():
    chrome_options = Options()
    chrome_options.add_argument("--headless")  # Runs Chrome in headless mode.
    chrome_options.add_argument("--disable-gpu")  # Disables GPU hardware acceleration. If software renderer is not in place, then the headless browser will fail.
    chrome_options.add_argument(f"--window-size={WIDTH}x{HEIGHT}")

    driver = webdriver.Chrome(service=ChromeService(ChromeDriverManager().install()), options=chrome_options)

    return driver


def create_solar_panel_array_from(polygon, namespaces) -> SolarPanelArray:
    coordinates = polygon.find('.//{http://www.opengis.net/kml/2.2}coordinates', namespaces)

    if coordinates is None:
        return None

    corners = extract_corners_from(coordinates)
    azimuth_degs = calc_solar_array_heading_from(corners)
    location = centroid(corners)
    area_m2 = calc_area_m2(corners)
    energy_gen = calc_energy_generated(area_m2, location, azimuth_degs)

    panel_array = SolarPanelArray(location, azimuth_degs, area_m2, energy_gen)

    return panel_array


def calc_energy_generated(area_m2, location, azimuth_degs):
    # Assumptions
    roof_pitch_degs = 30
    panel_efficiency_0_1 = 0.18
    gen_watts_per_m2 = 1000
    panel_degredation_rate_0_1 = 0.00608
    panel_age_yrs = 5

    # todo: use location and azimuth to determine this value
    kwh_over_kwp = 780 # Leeds value

    # First, we need to find the elevated area of the panels. To do this, we conduct the calculation: Measured Panel Area ÷ sin30
    elevated_area_m2 = area_m2 / math.cos(math.radians(roof_pitch_degs))

    # All panels are rated at 1000 w/m², so we multiply this by 1000 = 44,940.
    peak_array_gen_watts = elevated_area_m2 * gen_watts_per_m2 * panel_efficiency_0_1

    # We then need to calculate what this array will generate. We need the kWh/kWp value for this area, which for Leeds is around 780 (we can have one value for each MCS area- not too difficult).
    # We multiply the kWp by this value: 8 x 780 = 6240 kWh/annum.
    array_gen_kW = peak_array_gen_watts * kwh_over_kwp / 1000

    # This will reduce slightly year-on-year, so let's assume these panels are 5 years old. At a yearly degradation rate of 0.608%, we lose 3.04% (this can be another constant). Therefore, we multiply this generation by 0.9696 = 6050 kWh/year.
    degraded_array_gen_watts = array_gen_kW * (1 - panel_degredation_rate_0_1 * panel_age_yrs)

    return degraded_array_gen_watts


def extract_corners_from(coordinates) -> List[Location]:
    points = coordinates.text.strip().split(' ')

    corners = []
    for p in points:
        lon_str, lat_str, _ = p.strip().split(',')

        lat = float(lat_str)
        lon = float(lon_str)

        corner = Location(lat, lon)
        corners.append(corner)

    return corners


def calc_solar_array_heading_from(corners):
    # During labelling we've said that the first two points line up with the heading of the array
    array_edge_start = corners[0]
    array_edge_end = corners[1]

    azumith = calc_normal_azimuth_between(array_edge_start, array_edge_end)

    # todo: check if the absolute azimuth is greater than 90 degrees, then the
    # array is facing north to some degree

    return azumith


def calc_normal_azimuth_between(edge_start, edge_end):
    bearing = calc_bearing(edge_start, edge_end)
    # Get the normal to the bearing (perpendicular)
    normal_heading = (bearing + 90) % 360  # You can also subtract 90 if necessary

    return 180 - normal_heading


def calc_bearing(edge_start, edge_end):
    # Convert latitude and longitude from degrees to radians
    lat1, lon1, lat2, lon2 = map(math.radians, [edge_start.latitude, edge_start.longitude, edge_end.latitude, edge_end.longitude])

    # Calculate the bearing
    dLon = lon2 - lon1
    x = math.cos(lat2) * math.sin(dLon)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dLon)
    initial_bearing = math.atan2(x, y)

    # Convert from radians to degrees and normalize to 0 - 360 degrees
    initial_bearing = math.degrees(initial_bearing)
    initial_bearing = (initial_bearing + 360) % 360

    return initial_bearing


def calc_area_m2(points_lat_lon: List[Location]):
    # todo: this area calculation returns a result that is 97% of the value
    # displayed on google earth. this was tested on a panel-array-sized
    # rectangle and a neighbourhood-sized rectangle (safe to use for now, but we
    # should investigate this difference)

    if len(points_lat_lon) < 3:  # Need at least 3 points to form a polygon
        return 0

    # Define the projection: WGS84 Latitude/Longitude and UTM
    wgs84 = Proj(init='epsg:4326')
    utm = Proj(init='epsg:32633')  # You might need to change the UTM zone

    def to_utm(loc: Location):
        return transform(wgs84, utm, loc.longitude, loc.latitude)

    # Convert points to UTM
    utm_points = [to_utm(loc) for loc in points_lat_lon]

    # Calculate area using the Shoelace formula
    area = 0.0
    for i in range(len(utm_points)):
        x0, y0 = utm_points[i]
        x1, y1 = utm_points[(i + 1) % len(utm_points)]
        area += x0 * y1 - x1 * y0

    return abs(area) / 2.0


def take_google_earth_screenshot(url: str, screenshot_path: Path, driver):
    driver.get(url)
    time.sleep(5.5)

    clear_map_window_area(driver)

    driver.save_screenshot(screenshot_path)

    img = Image.open(screenshot_path)
    cropped_img = crop(img)
    cropped_img.save(screenshot_path)


def clear_map_window_area(driver):
    actions = ActionChains(driver)

    hide_modal_and_sidebar(actions)
    # close_top_bar(actions)


def hide_modal_and_sidebar(actions):
    # Hide modal
    actions.send_keys(Keys.ESCAPE).perform()
    time.sleep(0.3);

    # Hide sidebar
    actions.send_keys(Keys.ESCAPE).perform()
    time.sleep(0.3);


def close_top_bar(actions):
    x_coordinate = 1892
    y_coordinate = 25

    # Click the "X" in top right of screen
    actions.move_by_offset(x_coordinate, y_coordinate).click().perform()
    time.sleep(0.3);


def crop(img):
    vertical_padding = 140 # to remove the top bar and bottom icons
    image_height = HEIGHT - vertical_padding * 2
    horizontal_padding = (WIDTH - image_height) / 2
    crop_area = (horizontal_padding, vertical_padding, WIDTH - horizontal_padding, HEIGHT - vertical_padding) # left, upper, right, lower

    cropped_img = img.crop(crop_area)

    return cropped_img


# def add_debug_markers_to(cropped_img, array_heading_degs: float):
#     centre_x, centre_y = cropped_img.width // 2, cropped_img.height // 2
#     draw = ImageDraw.Draw(cropped_img)

#     add_heading_indicator_to(array_heading_degs, centre_x, centre_y, draw)
#     add_centre_marker_to(centre_x, centre_y, draw)
#     highlight_panel_array_area(cropped_img, draw)


# def add_heading_indicator_to(heading, centre_x, centre_y, draw):
#     heading_radians = math.radians((90 - heading) % 360)

#     # Length of the line
#     line_length = 100  # Adjust as needed

#     # Calculate end point of the line
#     end_x = centre_x + line_length * math.cos(heading_radians)
#     end_y = centre_y + line_length * math.sin(heading_radians)

#     # Draw the line
#     draw.line([centre_x, centre_y, end_x, end_y], fill="blue", width=3)


# def add_centre_marker_to(centre_x, centre_y, draw):
#     dot_size = 8
#     dot_color = "red"

#     top_left = (centre_x - dot_size // 2, centre_y - dot_size // 2)
#     bottom_right = (centre_x + dot_size // 2, centre_y + dot_size // 2)

#     draw.ellipse([top_left, bottom_right], fill=dot_color)


# def highlight_panel_array_area(cropped_img, draw):
#     # todo: add some debug view on top of the
#     return False


if __name__ == '__main__':
    main()