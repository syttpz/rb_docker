#!/usr/bin/env python3
# DualSense buttons -> Create 3 actions + speed adjust
#   triangle (button 3)  -> /dock
#   circle   (button 1)  -> /undock
#   dpad up/down    (11/12) -> linear speed  +/- 0.05 m/s
#   dpad right/left (14/13) -> angular speed +/- 0.2 rad/s
#
# Speed changes are applied live to /teleop_twist_joy_node parameters
# (normal + turbo scales together).

import rclpy
from rclpy.action import ActionClient
from rclpy.node import Node
from rcl_interfaces.msg import Parameter, ParameterType, ParameterValue
from rcl_interfaces.srv import SetParameters
from sensor_msgs.msg import Joy

from irobot_create_msgs.action import Dock, Undock

TRIANGLE = 3
CIRCLE = 1
DPAD_UP = 11
DPAD_DOWN = 12
DPAD_LEFT = 13
DPAD_RIGHT = 14

LIN_STEP, LIN_MIN, LIN_MAX = 0.05, 0.05, 0.46   # Create 3 max ~0.46 m/s
ANG_STEP, ANG_MIN, ANG_MAX = 0.2, 0.2, 1.9      # Create 3 max ~1.9 rad/s
TURBO_LIN = 2.0   # turbo = 2x linear
TURBO_ANG = 1.5   # turbo = 1.5x angular


class PadButtons(Node):
    def __init__(self):
        super().__init__('pad_buttons')
        self._dock = ActionClient(self, Dock, 'dock')
        self._undock = ActionClient(self, Undock, 'undock')
        self._set_params = self.create_client(
            SetParameters, '/teleop_twist_joy_node/set_parameters')
        self._lin = 0.3   # must match dualsense.yaml scale_linear.x
        self._ang = 1.0   # must match dualsense.yaml scale_angular.yaw
        self._prev = {}
        self.create_subscription(Joy, 'joy', self._on_joy, 10)
        self.get_logger().info(
            'triangle=dock circle=undock | dpad up/down=linear+- left/right=angular-+')

    def _rising_edge(self, msg, idx):
        now = len(msg.buttons) > idx and msg.buttons[idx] == 1
        was = self._prev.get(idx, False)
        self._prev[idx] = now
        return now and not was

    def _on_joy(self, msg):
        if self._rising_edge(msg, TRIANGLE):
            self._send_action(self._dock, Dock.Goal(), 'dock')
        if self._rising_edge(msg, CIRCLE):
            self._send_action(self._undock, Undock.Goal(), 'undock')

        changed = False
        if self._rising_edge(msg, DPAD_UP):
            self._lin = min(round(self._lin + LIN_STEP, 3), LIN_MAX)
            changed = True
        if self._rising_edge(msg, DPAD_DOWN):
            self._lin = max(round(self._lin - LIN_STEP, 3), LIN_MIN)
            changed = True
        if self._rising_edge(msg, DPAD_RIGHT):
            self._ang = min(round(self._ang + ANG_STEP, 3), ANG_MAX)
            changed = True
        if self._rising_edge(msg, DPAD_LEFT):
            self._ang = max(round(self._ang - ANG_STEP, 3), ANG_MIN)
            changed = True
        if changed:
            self._push_scales()

    def _push_scales(self):
        if not self._set_params.service_is_ready():
            self.get_logger().warning('teleop param service not ready')
            return
        req = SetParameters.Request()
        for name, value in (
            ('scale_linear.x', self._lin),
            ('scale_linear_turbo.x', min(self._lin * TURBO_LIN, LIN_MAX)),
            ('scale_angular.yaw', self._ang),
            ('scale_angular_turbo.yaw', min(self._ang * TURBO_ANG, ANG_MAX)),
        ):
            req.parameters.append(Parameter(
                name=name,
                value=ParameterValue(
                    type=ParameterType.PARAMETER_DOUBLE, double_value=value)))
        self._set_params.call_async(req)
        self.get_logger().info(
            f'speed: linear {self._lin:.2f} m/s, angular {self._ang:.2f} rad/s')

    def _send_action(self, client, goal, name):
        if not client.wait_for_server(timeout_sec=1.0):
            self.get_logger().warning(f'{name} action server not available')
            return
        self.get_logger().info(f'sending {name} goal')
        client.send_goal_async(goal)


def main():
    rclpy.init()
    node = PadButtons()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
