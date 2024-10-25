import random
from datetime import datetime, timedelta

CAPTCHA_LENGTH_MIN = 4
CAPTCHA_LENGTH_MAX = 6

async def generate_captcha():
    code = ''.join([str(random.randint(0, 9)) for _ in range(random.randint(CAPTCHA_LENGTH_MIN, CAPTCHA_LENGTH_MAX))])
    return code

def verify_captcha(user_input, real_code):
    return user_input == real_code
