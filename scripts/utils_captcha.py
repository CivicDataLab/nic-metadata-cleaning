import easyocr
import cv2
import logging
import warnings


logging.basicConfig(
    filename="captcha-status.log",
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
# Suppress easyocr and underlying library warnings
warnings.filterwarnings("ignore")
logging.getLogger("easyocr").setLevel(logging.ERROR)
logging.getLogger("PIL").setLevel(logging.ERROR)

def solve_captcha(image_path):
    #upscale the image first
    img = cv2.imread(image_path)
    img = cv2.resize(img, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
    cv2.imwrite("upscaled.png", img)
    # OCR
    reader = easyocr.Reader(['en'], gpu=False, verbose=False)
    result = reader.readtext("upscaled.png", detail=0, allowlist='ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789')

    result = ''.join(result)
    result = "".join(result.split())
    print(result)
    
    return result
