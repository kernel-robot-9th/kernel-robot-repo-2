from glob import glob

from setuptools import find_packages, setup

package_name = 'pinky_marker'

setup(
    name=package_name,
    version='0.1.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        ('share/' + package_name + '/config', glob('config/*.yaml')),
        ('share/' + package_name + '/launch', glob('launch/*.py')),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='pinky',
    maintainer_email='dev@example.com',
    description='Pinky onboard camera and ArUco nurse follower',
    license='Proprietary',
    entry_points={
        'console_scripts': [
            'camera = pinky_marker.camera_node:main',
            'nurse_follower = pinky_marker.follower_node:main',
        ],
    },
)
