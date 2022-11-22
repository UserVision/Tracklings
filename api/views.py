from skimage.metrics import structural_similarity
import numpy
import cv2
from selenium.webdriver.common.by import By
from selenium import webdriver
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import InMemoryUploadedFile
from rest_framework.status import *
from rest_framework.response import Response
from rest_framework.decorators import api_view
import math
import os
import time
from difflib import SequenceMatcher
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


class ErrorMessages:
    ERROR_MISSING_INFO = "Missing Information"
    ERROR_INVALID_DATA = "Invalid Data Sent"


device_types = {
    "desktop": "1920x1080",
    "mobile": "414x736",
    "tablet": "800x1280"
}


def get_image_changes(img_path1, img_path2, hash_key, host):
    img1 = cv2.imread(img_path1)
    img2 = cv2.imread(img_path2)

    if (img1.shape != img2.shape):
        smaller_img = img1 if img1.shape < img2.shape else img2
        big_image = img1 if img1.shape > img2.shape else img2
        # big_image = img1 if smaller_img == img1 else img2

        bottom_padding = big_image.shape[0] - smaller_img.shape[0]
        right_padding = big_image.shape[1] - smaller_img.shape[1]
        smaller_img = cv2.copyMakeBorder(
            smaller_img, 0, bottom_padding, 0, right_padding, cv2.BORDER_CONSTANT, value=[255, 255, 255])

    else:
        smaller_img, big_image = img1, img2

    res = cv2.absdiff(smaller_img, big_image)
    res = res.astype(numpy.uint8)

    percentage = (numpy.count_nonzero(res) * 100) / res.size

    before = big_image
    after = smaller_img

    before_gray = cv2.cvtColor(before, cv2.COLOR_BGR2GRAY)
    after_gray = cv2.cvtColor(after, cv2.COLOR_BGR2GRAY)

    (score, diff) = structural_similarity(before_gray, after_gray, full=True)

    diff = (diff * 255).astype("uint8")

    diff_box = cv2.merge([diff, diff, diff])

    os.mkdir(str(BASE_DIR / f'media/diff_box/{hash_key}'))
    cv2.imwrite(
        str(BASE_DIR / f"media/diff_box/{hash_key}/diffBox.png"), diff_box)

    thresh = cv2.threshold(
        diff, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)[1]
    contours = cv2.findContours(
        thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    contours = contours[0] if len(contours) == 2 else contours[1]

    spottedChanges = []
    for i, coordinates in enumerate(contours):
        area = cv2.contourArea(coordinates)
        if area > 40:
            x, y, w, h = cv2.boundingRect(coordinates)
            crop_img = after[y:y+h, x:x+w]
            cv2.imwrite(
                str(BASE_DIR / f"media/output/{hash_key}/changesDetected{i}.png"), crop_img)
            spottedChanges.append({
                "imageURL": host + "/" + f"media/output/{hash_key}/changesDetected{i}.png",
                "coordinates": [(x, y), (x+w, y), (x, y+h), (x+w, y+h)]
            })

    return (percentage, spottedChanges, host + "/" + f"media/diff_box/{hash_key}/diffBox.png")


def get_text_change_percentage(text1, text2):
    textChangeValue = SequenceMatcher(None, text1, text2)
    textPercentChange = 100 - textChangeValue.ratio() * 100

    return textPercentChange


@api_view(['POST'])
def ping(request):
    url = request.data.get("url")
    device_type = request.data.get("deviceType")
    try:
        device_type = device_type.lower()
    except:
        pass
    image = request.data.get("image")
    large_text = request.data.get("largeText")

    if not url or not device_type:
        return Response({"error": ErrorMessages.ERROR_MISSING_INFO}, status=HTTP_200_OK)
    if type(url) != str or type(device_type) != str or device_type not in ["desktop", "mobile", "tablet"] or type(image) not in [InMemoryUploadedFile, type(None)] or type(large_text) not in [str, type(None)]:
        return Response({"error": ErrorMessages.ERROR_INVALID_DATA}, status=HTTP_200_OK)

    response = {
        "imageURL": "",
        "largeText": "",
        "imagePercentChange": "",
        "textPercentChange": "",
        "spottedChanges": [],
        "overallDifference": ""
    }

    page_width, page_height = int(device_types[device_type].split(
        "x")[0]), int(device_types[device_type].split("x")[1])

    hash_key = math.floor(time.time() * 1000)
    os.mkdir(str(BASE_DIR / f'media/output/{hash_key}'))
    path = str(
        BASE_DIR / f"media/output/{hash_key}/output{device_types[device_type]}.png")

    chrome_options = webdriver.ChromeOptions()
    chrome_options.add_experimental_option("mobileEmulation", {
        "deviceMetrics": {"width": page_width, "height": page_height, "pixelRatio": 3.0}})
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--disable-gpu")
    driver = webdriver.Chrome(chrome_options=chrome_options)
    driver.get(url)
    required_width = driver.execute_script(
        'return document.body.parentNode.scrollWidth')
    required_height = driver.execute_script(
        'return document.body.parentNode.scrollHeight')
    driver.set_window_size(required_width, required_height)
    body = driver.find_element(By.TAG_NAME, "body")
    body.screenshot(path)
    page_source = driver.page_source
    driver.quit()

    response["imageURL"] = request.get_host(
    ) + "/" + f"media/output/{hash_key}/output{device_types[device_type]}.png"
    response["largeText"] = page_source

    response["textPercentChange"] = get_text_change_percentage(
        large_text, page_source) if large_text else "100"

    if image:
        os.mkdir(str(BASE_DIR / f"media/input/{hash_key}"))
        path2 = str(
            BASE_DIR / f"media/input/{hash_key}/input{device_types[device_type]}.png")
        saved_input_image = default_storage.save(
            str(BASE_DIR / f"media/input/{hash_key}/input{device_types[device_type]}.png"), ContentFile(image.read()))

        data = get_image_changes(
            path, path2, hash_key, request.get_host())

    response["imagePercentChange"], response['spottedChanges'], response['overallDifference'] = (
        data[0], data[1], data[2]) if image else ("100", [], "")

    return Response(response, status=HTTP_200_OK)
