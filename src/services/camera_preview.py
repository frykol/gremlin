import asyncio

import cv2

from src.robot_state import RobotState


class CameraPreview:
    def __init__(
        self,
        state: RobotState,
        window_name: str = "Niezawodne Sterowanie Robotem",
    ):
        self.state = state
        self.window_name = window_name
        self.running = True

    async def run(self):
        print("Sterowanie gestami: 's' = stream on/off, 'q' = wyjscie")

        while self.running:
            frame = self.state.last_frame

            if frame is not None:
                display = (
                    self.state.display_frame.copy()
                    if self.state.display_frame is not None
                    else frame.image.copy()
                )
                stream_label = "STREAM: ON" if self.state.stream_enabled else "STREAM: OFF"
                cv2.putText(
                    display,
                    f"{stream_label} | s=toggle | q=quit",
                    (10, display.shape[0] - 20),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.6,
                    (200, 200, 200),
                    1,
                )
                cv2.imshow(self.window_name, display)

            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                self.running = False
                break
            if key == ord("s"):
                self.state.stream_enabled = not self.state.stream_enabled
                print(f"Stream: {'ON' if self.state.stream_enabled else 'OFF'}")

            await asyncio.sleep(0.001)

        cv2.destroyAllWindows()
