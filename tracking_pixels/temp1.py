from PIL import Image
import os

def generate_tracking_pixel():
    os.makedirs('tracking_pixels', exist_ok=True)
    img = Image.new('RGB', (50, 50), (255, 255, 255))
    img.save('tracking_pixels/pixil1.png')

generate_tracking_pixel()