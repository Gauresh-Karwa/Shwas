import re

def slugify(name: str) -> str:
    slug = name.lower()
    slug = re.sub('[^a-z0-9]+', '-', slug)
    return slug.strip('-')
