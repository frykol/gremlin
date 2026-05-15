import time
import cv2
from .config import load_config
from .hardware.oak_d.dummy_oak_d import FakeOakDCamera
from .hardware.i2c.i2c_pwm import i2cPWM
from .hardware.gpio.gpio_controller import GPIOController

def switch(i2c, ch, pwm):
    for i in range(0, 4):
       i2c.set_pwm(i,0,0)
    i2c.set_pwm(ch, 0, pwm)
        
def loop():
    config = load_config("config.json")
    oak_d_config = config["oak_d"]
    oak_d_camera = FakeOakDCamera(oak_d_config["width"], oak_d_config["height"])

    oak_d_camera.start()
    gpio_c = GPIOController()
    gpio_c.setup()
    gpio_c.set_pin("R_EN", True)
    gpio_c.set_pin("L_EN", True)
    
    i2c_p = i2cPWM()
    i2c_p.start()
    counter = 0
    try:
        while True:
            switch(i2c_p, counter, 2000)
            counter += 1
            counter %= 4
            time.sleep(2)
    finally:
        i2c_p.set_pwm(0,0,0)
        i2c_p.set_pwm(1,0,0)
        i2c_p.set_pwm(2,0,0)
        i2c_p.set_pwm(3,0,0)
        oak_d_camera.stop()

def main():
    loop()

if __name__ == "__main__":
    main()
