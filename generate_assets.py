import os
from PIL import Image, ImageDraw

def create_banner():
    # System 7 stripes banner
    img = Image.new('RGB', (500, 60), color='#CCCCCC')
    draw = ImageDraw.Draw(img)
    for i in range(0, 60, 4):
        draw.line([(0, i), (500, i)], fill='#999999', width=1)
    img.save('installer/qtifw/resources/images/banner.png')

def create_watermark():
    # Side watermark with pattern
    img = Image.new('RGB', (164, 314), color='#CCCCCC')
    draw = ImageDraw.Draw(img)
    # Checkerboard pattern
    for y in range(0, 314, 2):
        for x in range(0, 164, 2):
            if (x + y) % 4 == 0:
                draw.point((x, y), fill='#999999')
    img.save('installer/qtifw/resources/images/watermark.png')

def create_logo():
    # Try to use the official logo and pixelate it
    source_logo = 'assets/icons/app.png'

    if os.path.exists(source_logo):
        try:
            img = Image.open(source_logo).convert('RGBA')
            # Create a white/grey background for System 7 look
            bg = Image.new('RGBA', img.size, (204, 204, 204, 255)) # #CCCCCC
            img = Image.alpha_composite(bg, img).convert('L') # Convert to Grayscale

            # Pixelate: resize to 64x64 then back to 128x128
            img = img.resize((64, 64), resample=Image.NEAREST)
            img = img.resize((128, 128), resample=Image.NEAREST)

            # Add a black border
            draw = ImageDraw.Draw(img)
            draw.rectangle([0, 0, 127, 127], outline=0, width=2)

            img.save('installer/qtifw/resources/images/logo.png')
            print(f"Logo generated from {source_logo}")
            return
        except Exception as e:
            print(f"Error processing logo: {e}")

    # Fallback to generated M if source not found
    img = Image.new('L', (128, 128), color=204)
    draw = ImageDraw.Draw(img)
    draw.rectangle([20, 20, 108, 108], outline=0, width=2)
    points = [(30, 90), (30, 40), (64, 70), (98, 40), (98, 90)]
    draw.line(points, fill=0, width=8)
    img.save('installer/qtifw/resources/images/logo.png')
    print("Fallback logo generated.")

if __name__ == "__main__":
    target_dir = 'installer/qtifw/resources/images'
    os.makedirs(target_dir, exist_ok=True)
    create_banner()
    create_watermark()
    create_logo()
    print("Assets generated successfully.")
