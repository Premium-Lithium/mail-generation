import time
import math

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

    driver.quit();


def create_solar_panel_array_from(polygon, namespaces):
    coordinates = polygon.find('.//{http://www.opengis.net/kml/2.2}coordinates', namespaces)

    if coordinates is None:
        return None

    corners = extract_corners_from(coordinates)

    heading_degs = calc_solar_array_heading_from(corners)
    latitude, longitude = centroid(corners)
    area = 1234 # todo: calculate area from corners

    panel_array = {
        "latitude": latitude,
        "longitude": longitude,
        "heading_degs": heading_degs,
        "area": area
    }

    return panel_array


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

    heading = calculate_normal_heading(lat_0, lon_0, lat_1, lon_1)

    return heading


def calculate_normal_heading(lat1, lon1, lat2, lon2):
    bearing = calculate_bearing(lat1, lon1, lat2, lon2)
    # Get the normal to the bearing (perpendicular)
    normal_heading = (bearing + 90) % 360  # You can also subtract 90 if necessary

    return 180 - normal_heading


def calculate_bearing(lat1, lon1, lat2, lon2):
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
    add_markers_to(cropped_img, array_heading_degs)

    cropped_img.save(image_path)


def crop(img):
    vertical_padding = 140 # to remove the top bar and bottom icons
    image_height = HEIGHT - vertical_padding * 2
    horizontal_padding = (WIDTH - image_height) / 2
    crop_area = (horizontal_padding, vertical_padding, WIDTH - horizontal_padding, HEIGHT - vertical_padding) # left, upper, right, lower

    cropped_img = img.crop(crop_area)

    return cropped_img


def add_markers_to(cropped_img, array_heading_degs: float):
    centre_x, centre_y = cropped_img.width // 2, cropped_img.height // 2
    draw = ImageDraw.Draw(cropped_img)

    add_heading_indicator_to(array_heading_degs, centre_x, centre_y, draw)
    add_centre_marker_to(centre_x, centre_y, draw)


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


if __name__ == '__main__':
    main()