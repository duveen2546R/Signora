from PIL import Image, ImageDraw
import sys

img_path = "/Users/duveen/.gemini/antigravity/brain/80dff3a6-287b-41cc-a9e4-4ca70f2276c8/.user_uploaded/media_1791445616912_8db1e35a.png"
out_path = "/Users/duveen/.gemini/antigravity/brain/80dff3a6-287b-41cc-a9e4-4ca70f2276c8/annotated_graph.png"

try:
    img = Image.open(img_path)
    draw = ImageDraw.Draw(img)
    
    # The image is 1856 x 1030
    # Frame 60 is roughly at x=950. The valley is around x=850 to 950. The y is around 800.
    # Let's draw a big red bounding box and arrow pointing to the middle valley.
    
    width, height = img.size
    
    # Estimate the pixel coordinates of Frame 55, Velocity ~0.00
    # X axis goes from ~250 (frame 0) to ~1600 (frame 120)
    # Y axis goes from ~850 (velocity 0) to ~150 (velocity 0.06)
    
    # Frame 55 is roughly (55/120) * (1600-250) + 250 = 868
    # Velocity 0 is roughly 820
    
    x_center = 900
    y_center = 820
    
    # Draw a red circle
    radius = 40
    draw.ellipse((x_center - radius, y_center - radius, x_center + radius, y_center + radius), outline="red", width=8)
    
    # Draw a line/arrow pointing to it
    draw.line((x_center, y_center - 200, x_center, y_center - radius), fill="red", width=8)
    draw.text((x_center - 150, y_center - 250), "CLICK ANYWHERE\nIN THIS FLAT VALLEY", fill="red", font_size=40)
    
    img.save(out_path)
    print("Success")
except Exception as e:
    print(f"Error: {e}")

