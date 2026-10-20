from glob import glob

from setuptools import find_packages, setup

package_name = 'vla_teleop'

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
    description='Real OMX arm teleop tool: leader -> follower, coordinate viewer, point recording, error recovery',
    license='Proprietary',
    entry_points={'console_scripts': ['teleop = vla_teleop.cli:main']},
)
