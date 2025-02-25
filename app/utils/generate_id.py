from nanoid import generate


# LibreChat expects both file IDs and session IDs to match the regex pattern: ^[A-Za-z0-9_-]{21}$
# This means IDs must be exactly 21 characters long and only contain alphanumeric characters, underscores, and hyphens
def generate_id():
    alphabet = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
    return generate(alphabet, 21)
