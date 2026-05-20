import cv2
from config import load_config
from hardware.oak_d.dummy_oak_d import FakeOakDCamera

def loop():
    config = load_config("../config.json")
    oak_d_config = config["oak_d"]
    oak_d_camera = FakeOakDCamera(oak_d_config["width"], oak_d_config["height"])

    oak_d_camera.start()

    try:
        while True:
            frame = oak_d_camera.get_camera_frame()
            if frame is not None:
                image = frame.image
                cv2.imshow("Dummy", image)

                if cv2.waitKey(1) == ord("q"):
                    break
    finally:
        oak_d_camera.stop()
        cv2.destroyAllWindows()

def main():
    loop()

if __name__ == "__main__":
    main()
