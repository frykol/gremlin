import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Twist

PUBLISH_RATE_HZ = 20.0
LINEAR_SPEED = 0.3
ANGULAR_SPEED = 0.6

# gesture name -> (linear.x, linear.y, angular.z)
GESTURE_TWIST_MAP = {
    'forward': (LINEAR_SPEED, 0.0, 0.0),
    'backward': (-LINEAR_SPEED, 0.0, 0.0),
    'left': (0.0, 0.0, ANGULAR_SPEED),
    'right': (0.0, 0.0, -ANGULAR_SPEED),
    'stop': (0.0, 0.0, 0.0),
    'fist': (0.0, 0.0, 0.0),
    'peace': (0.0, 0.0, 0.0),
}


class GestureWorker:
    """Placeholder for the real OpenCV Zoo ONNX pipeline (MPPalmDet + MPHandPose).

    TODO: wire in the existing hand_gestures.py implementation here.
    It should open the OAK-D / camera stream, run palm detection + hand
    pose estimation via cv2.dnn, and expose the latest recognized gesture
    through get_gesture().
    """

    def __init__(self):
        pass

    def get_gesture(self):
        """Return the current gesture name (one of GESTURE_TWIST_MAP) or None."""
        # TODO: replace with real inference result
        return None

    def close(self):
        pass


class GestureNode(Node):

    def __init__(self):
        super().__init__('gesture_node')
        self.publisher_ = self.create_publisher(Twist, '/cmd_vel_gesture', 10)

        self._worker = GestureWorker()
        self._current_gesture = None

        # Republish at a fixed rate so downstream consumers (twist_mux) see
        # a live stream rather than one-shot commands.
        self._timer = self.create_timer(1.0 / PUBLISH_RATE_HZ, self._tick)

    def _tick(self):
        gesture = self._worker.get_gesture()
        if gesture is not None:
            self._current_gesture = gesture
        elif self._current_gesture is not None:
            # No hand detected this frame: fail safe to stop.
            self._current_gesture = 'stop'

        if self._current_gesture is None:
            return

        linear_x, linear_y, angular_z = GESTURE_TWIST_MAP.get(self._current_gesture, (0.0, 0.0, 0.0))
        twist = Twist()
        twist.linear.x = linear_x
        twist.linear.y = linear_y
        twist.angular.z = angular_z
        self.publisher_.publish(twist)

    def destroy_node(self):
        self._worker.close()
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = GestureNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
