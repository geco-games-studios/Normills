from io import BytesIO
from textwrap import wrap

from django.core.files.base import ContentFile
from django.utils.text import slugify
from PIL import Image, ImageDraw, ImageFont


PORTRAIT_SIZE = (1080, 1920)


def _hex_to_rgb(value, fallback):
    value = (value or '').strip().lstrip('#')
    if len(value) != 6:
        return fallback
    try:
        return tuple(int(value[index:index + 2], 16) for index in (0, 2, 4))
    except ValueError:
        return fallback


def _font(size):
    try:
        return ImageFont.truetype('arial.ttf', size)
    except OSError:
        return ImageFont.load_default()


def _draw_wrapped(draw, text, position, font, fill, max_chars, line_gap):
    x, y = position
    for line in wrap(text, width=max_chars) or ['']:
        draw.text((x, y), line, font=font, fill=fill)
        bbox = draw.textbbox((x, y), line, font=font)
        y += (bbox[3] - bbox[1]) + line_gap
    return y


def _cover_image(source, size):
    image = source.convert('RGB')
    image_ratio = image.width / image.height
    target_ratio = size[0] / size[1]
    if image_ratio > target_ratio:
        new_height = size[1]
        new_width = int(new_height * image_ratio)
    else:
        new_width = size[0]
        new_height = int(new_width / image_ratio)
    image = image.resize((new_width, new_height), Image.Resampling.LANCZOS)
    left = (new_width - size[0]) // 2
    top = (new_height - size[1]) // 2
    return image.crop((left, top, left + size[0], top + size[1]))


def generate_product_ad_image(product, template):
    width, height = PORTRAIT_SIZE
    background = _hex_to_rgb(template.background_color, (244, 239, 230))
    accent = _hex_to_rgb(template.accent_color, (17, 24, 39))
    frame = _hex_to_rgb(template.frame_color, (255, 255, 255))
    text = _hex_to_rgb(template.text_color, (17, 24, 39))

    canvas = Image.new('RGB', PORTRAIT_SIZE, background)
    draw = ImageDraw.Draw(canvas)

    draw.rectangle((0, 0, width, 520), fill=accent)
    draw.ellipse((-220, 180, 520, 920), fill=tuple(min(channel + 26, 255) for channel in background))
    draw.ellipse((650, 780, 1320, 1500), fill=tuple(max(channel - 20, 0) for channel in background))

    product_box = (120, 360, 960, 1220)
    draw.rounded_rectangle(
        (product_box[0] - 24, product_box[1] - 24, product_box[2] + 24, product_box[3] + 24),
        radius=44,
        fill=frame,
    )

    try:
        with product.image.open('rb') as image_file:
            product_image = Image.open(image_file)
            product_image.load()
    except Exception:
        product_image = Image.new('RGB', (840, 860), (230, 230, 230))

    product_image = _cover_image(product_image, (product_box[2] - product_box[0], product_box[3] - product_box[1]))
    canvas.paste(product_image, (product_box[0], product_box[1]))

    title_font = _font(74)
    store_font = _font(34)
    detail_font = _font(36)
    price_font = _font(70)
    cta_font = _font(34)

    draw.text((96, 90), 'NORMILS ONLINE', font=store_font, fill=frame)
    draw.text((96, 142), product.store.name.upper(), font=detail_font, fill=frame)

    y = 1280
    y = _draw_wrapped(draw, product.name, (96, y), title_font, text, max_chars=18, line_gap=10)
    y += 22
    paygo_line = ''
    if product.paygo_is_available:
        paygo_line = f"PayGo: start with K{product.paygo_min_deposit_amount:.2f}"
    else:
        paygo_line = f"{product.stock} available online" if product.stock > 0 else "Limited availability"
    _draw_wrapped(draw, paygo_line, (100, y), detail_font, text, max_chars=34, line_gap=8)

    tag_left, tag_top, tag_right, tag_bottom = 560, 1340, 980, 1548
    draw.rounded_rectangle((tag_left, tag_top, tag_right, tag_bottom), radius=34, fill=accent)
    draw.rounded_rectangle((tag_left + 12, tag_top + 12, tag_right - 12, tag_bottom - 12), radius=28, outline=frame, width=5)
    draw.text((tag_left + 42, tag_top + 36), 'PRICE', font=store_font, fill=frame)
    draw.text((tag_left + 42, tag_top + 88), f"K{product.price:.2f}", font=price_font, fill=frame)

    draw.rounded_rectangle((96, 1650, 984, 1776), radius=28, fill=frame)
    draw.text((132, 1690), 'View product on Normils Online', font=cta_font, fill=text)

    output = BytesIO()
    canvas.save(output, format='JPEG', quality=88, optimize=True)
    filename = f"{slugify(product.name) or 'product'}-portrait-ad.jpg"
    return ContentFile(output.getvalue(), name=filename)
