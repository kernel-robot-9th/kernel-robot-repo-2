from glob import glob

from setuptools import find_packages, setup

package_name = 'vla_executor'

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
    description='Top-down pick and place for OMX-F via MoveIt move_group',
    license='Proprietary',
    entry_points={
        'console_scripts': [
            'executor_node = vla_executor.executor_node:main',
        ],
    },
)
