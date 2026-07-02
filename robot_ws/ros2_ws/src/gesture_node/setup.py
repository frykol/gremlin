from setuptools import setup

package_name = 'gesture_node'

setup(
    name=package_name,
    version='0.1.0',
    packages=[package_name],
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='gremlin team',
    maintainer_email='dev@example.com',
    description='Hand gesture recognition (OpenCV Zoo ONNX) publishing Twist on /cmd_vel_gesture',
    license='MIT',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'gesture_node = gesture_node.gesture_node:main',
        ],
    },
)
