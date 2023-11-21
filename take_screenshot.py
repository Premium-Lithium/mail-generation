import time
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


WIDTH = 1920
HEIGHT = 1080
DEBUG_VIEW = False


def main():
    chrome_options = Options()
    chrome_options.add_argument("--headless")  # Runs Chrome in headless mode.
    chrome_options.add_argument("--disable-gpu")  # Disables GPU hardware acceleration. If software renderer is not in place, then the headless browser will fail.
    chrome_options.add_argument(f"--window-size={WIDTH}x{HEIGHT}")

    driver = webdriver.Chrome(service=ChromeService(ChromeDriverManager().install()), options=chrome_options)

    # Load and parse the XML
    tree = ET.parse('region-5.kml')
    root = tree.getroot()

    # Define the namespaces (important for finding elements)
    namespaces = {
        '': "http://www.opengis.net/kml/2.2",
        'gx': "http://www.google.com/kml/ext/2.2"
    }

    # Iterate over all placemarks
    solar_array_id = 0

    for placemark in root.findall('.//{http://www.opengis.net/kml/2.2}Placemark', namespaces):
        polygon = placemark.find('.//{http://www.opengis.net/kml/2.2}Polygon', namespaces)

        if polygon is not None:
            panel_array = create_solar_panel_array_from(polygon, namespaces)

            lat = panel_array["latitude"]
            lon = panel_array["longitude"]
            heading = panel_array["heading_degs"]

            print(f"Taking screenshot for solar panel array {solar_array_id} at {lat}, {lon} with heading {heading}")
            img_path = f"{solar_array_id}_{heading}.png"
            screenshot_solar_panel_array_at(lat, lon, driver, img_path, heading)

            solar_array_id += 1

            # put stuff on supabase


    driver.quit();


def create_solar_panel_array_from(polygon, namespaces):
    coordinates = polygon.find('.//{http://www.opengis.net/kml/2.2}coordinates', namespaces)

    if coordinates is None:
        return None

    corners = extract_corners_from(coordinates)

    azimuth_degs = calc_solar_array_heading_from(corners)
    latitude, longitude = centroid(corners)
    area_m2 = calc_area_m2(corners)
    savings_gbp = calc_savings_gbp(area_m2, latitude, longitude, azimuth_degs, print_results=True)

    panel_array = {
        "latitude": latitude,
        "longitude": longitude,
        "heading_degs": azimuth_degs,
        "area": area_m2,
        "savings_gbp": savings_gbp
    }

    return panel_array


def calc_savings_gbp(area_m2, lat, lon, azimuth_degs, print_results=False):
    # Assumptions
    roof_pitch_degs = 30
    panel_efficiency_0_1 = 0.18
    gen_watts_per_m2 = 1000
    panel_degredation_rate_0_1 = 0.00608
    panel_age_yrs = 5
    battery_usage_multiplier = 0.4 # In Half Day
    unit_rate_gbp_per_kwh = 0.28

    # todo: use lat/lon and azimuth to determine this value
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

    # We will assume an occupancy archetype of In Half Day (for diplomacy), so we can also have the Battery Usage Multiplier as a constant of 0.4. Therefore, we multiply this figure by 0.4 = 2420 kWh/annum.
    solar_energy_used_by_battery = degraded_array_gen_watts * battery_usage_multiplier

    # We will use a constant unit rate of 28p/kWh (0.28), so to get the savings, we multiply by this constant: £677.60.
    savings_gbp = solar_energy_used_by_battery * unit_rate_gbp_per_kwh

    if print_results:
        print(f"{elevated_area_m2=:0.2f}")
        print(f"{peak_array_gen_watts=:0.2f}")
        print(f"{array_gen_kW=:0.2f}")
        print(f"{degraded_array_gen_watts=:0.2f}")
        print(f"{solar_energy_used_by_battery=:0.2f}")
        print(f"{savings_gbp=:0.2f}")

    return savings_gbp


def extract_corners_from(coordinates):
    points = coordinates.text.strip().split(' ')

    corners = []
    for p in points:
        lon_str, lat_str, _ = p.strip().split(',')

        lat = float(lat_str)
        lon = float(lon_str)

        corner = (lat, lon)
        corners.append(corner)

    return corners


def calc_solar_array_heading_from(corners):
    # During labelling we've said that the first two points line up with the heading of the array
    lat_0, lon_0 = corners[0]
    lat_1, lon_1 = corners[1]

    azumith = calc_normal_azimuth(lat_0, lon_0, lat_1, lon_1)

    # todo: check if the absolute azimuth is greater than 90 degrees, then the
    # array is facing north to some degree

    return azumith


def calc_normal_azimuth(lat1, lon1, lat2, lon2):
    bearing = calc_bearing(lat1, lon1, lat2, lon2)
    # Get the normal to the bearing (perpendicular)
    normal_heading = (bearing + 90) % 360  # You can also subtract 90 if necessary

    return 180 - normal_heading


def calc_bearing(lat1, lon1, lat2, lon2):
    # Convert latitude and longitude from degrees to radians
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])

    # Calculate the bearing
    dLon = lon2 - lon1
    x = math.cos(lat2) * math.sin(dLon)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dLon)
    initial_bearing = math.atan2(x, y)

    # Convert from radians to degrees and normalize to 0 - 360 degrees
    initial_bearing = math.degrees(initial_bearing)
    initial_bearing = (initial_bearing + 360) % 360

    return initial_bearing


def calc_area_m2(points_lat_lon):
    # todo: this area calculation returns a result that is 97% of the value
    # displayed on google earth. this was tested on a panel-array-sized
    # rectangle and a neighbourhood-sized rectangle (safe to use for now, but we
    # should investigate this difference)

    if len(points_lat_lon) < 3:  # Need at least 3 points to form a polygon
        return 0

    # Define the projection: WGS84 Latitude/Longitude and UTM
    wgs84 = Proj(init='epsg:4326')
    utm = Proj(init='epsg:32633')  # You might need to change the UTM zone

    def to_utm(lat, lon):
        return transform(wgs84, utm, lon, lat)

    # Convert points to UTM
    utm_points = [to_utm(lat, lon) for lat, lon in points_lat_lon]

    # Calculate area using the Shoelace formula
    area = 0.0
    for i in range(len(utm_points)):
        x0, y0 = utm_points[i]
        x1, y1 = utm_points[(i + 1) % len(utm_points)]
        area += x0 * y1 - x1 * y0

    return abs(area) / 2.0


def centroid(points):
    if not points:
        return None

    lat_sum, lon_sum = 0, 0
    for (lat, lon) in points:
        lat_sum += lat
        lon_sum += lon

    centroid_lat = lat_sum / len(points)
    centroid_lon = lon_sum / len(points)

    return (centroid_lat, centroid_lon)


def screenshot_solar_panel_array_at(lat: float, lon: float, driver, img_path, array_heading_degs: float) -> Path:
    """Take a screenshot of property at the given latitude and longitude"""
    load_google_earth_at(lat, lon, driver)
    clear_map_window_area(driver)
    take_screenshot(img_path, driver, array_heading_degs)


def load_google_earth_at(lat, lon, driver):
    distance = 2000
    verticalFoV_degs = 35
    heading = 0 # Facing due north

    # todo: determine tilt and lat offset from google earth coverage map API (0 if 2D, 45 if 3D)
    has_3d_map_view = True

    tilt = 45 if has_3d_map_view else 0
    lat_offset = 0.00016 if has_3d_map_view else 0

    # url = f"https://earth.google.com/web/@{lat},{lon},{altitude}a,{distance}d,{yaw}y,{heading}h,{tilt}t,0r"
    url = f"https://earth.google.com/web/@{lat + lat_offset},{lon},{distance}d,{math.radians(verticalFoV_degs)}y,{heading}h,{tilt}t,0r"
    print(url)

    driver.get(url)
    time.sleep(5.5)


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


def take_screenshot(image_path: Path, driver, array_heading_degs: float):
    driver.save_screenshot(image_path)

    img = Image.open(image_path)

    cropped_img = crop(img)

    if DEBUG_VIEW:
        add_debug_markers_to(cropped_img, array_heading_degs)

    cropped_img.save(image_path)


def crop(img):
    vertical_padding = 140 # to remove the top bar and bottom icons
    image_height = HEIGHT - vertical_padding * 2
    horizontal_padding = (WIDTH - image_height) / 2
    crop_area = (horizontal_padding, vertical_padding, WIDTH - horizontal_padding, HEIGHT - vertical_padding) # left, upper, right, lower

    cropped_img = img.crop(crop_area)

    return cropped_img


def add_debug_markers_to(cropped_img, array_heading_degs: float):
    centre_x, centre_y = cropped_img.width // 2, cropped_img.height // 2
    draw = ImageDraw.Draw(cropped_img)

    add_heading_indicator_to(array_heading_degs, centre_x, centre_y, draw)
    add_centre_marker_to(centre_x, centre_y, draw)
    highlight_panel_array_area(cropped_img, draw)


def add_heading_indicator_to(heading, centre_x, centre_y, draw):
    heading_radians = math.radians((90 - heading) % 360)

    # Length of the line
    line_length = 100  # Adjust as needed

    # Calculate end point of the line
    end_x = centre_x + line_length * math.cos(heading_radians)
    end_y = centre_y + line_length * math.sin(heading_radians)

    # Draw the line
    draw.line([centre_x, centre_y, end_x, end_y], fill="blue", width=3)


def add_centre_marker_to(centre_x, centre_y, draw):
    dot_size = 8
    dot_color = "red"

    top_left = (centre_x - dot_size // 2, centre_y - dot_size // 2)
    bottom_right = (centre_x + dot_size // 2, centre_y + dot_size // 2)

    draw.ellipse([top_left, bottom_right], fill=dot_color)


def calc_savings(array_area_m2: float, array_heading: float) -> float:
    # todo: use spreadsheet model from chris to work out what the savings could be for this property
    return 1234


def highlight_panel_array_area(cropped_img, draw):
    # todo: add some debug view on top of the
    return False


if __name__ == '__main__':
    main()