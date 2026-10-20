from glob import glob

from setuptools import find_packages, setup

package_name = 'robot_monitor'

setup(
    name=package_name,
    version='0.1.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        ('share/' + package_name + '/config', glob('config/*.yaml')),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='fastcamp1',
    maintainer_email='leval5716@gmail.com',
    description='Robot monitor for the control server: battery, pose, navigation state of each robot',
    license='Proprietary',
    entry_points={
        'console_scripts': [
            'monitor = robot_monitor.monitor_node:main',
        ],
    },
)
