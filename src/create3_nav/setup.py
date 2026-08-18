import os
from glob import glob

from setuptools import setup

package_name = 'create3_nav'

setup(
    name=package_name,
    version='0.0.1',
    packages=[package_name],
    data_files=[
        ('share/ament_index/resource_index/packages',
         ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        # Launch and config, installed so `ros2 launch create3_nav ...` works.
        (os.path.join('share', package_name, 'launch'), glob('launch/*.launch.py')),
        (os.path.join('share', package_name, 'config'), glob('config/*')),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='syttpz',
    maintainer_email='bhu7035@gmail.com',
    description='Local Create 3 navigation: RPLIDAR A2M12 bringup and nav2 patrol.',
    license='TODO',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            # patrol node added in a later step
        ],
    },
)
