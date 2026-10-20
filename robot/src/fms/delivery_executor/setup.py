from glob import glob

from setuptools import find_packages, setup

package_name = 'delivery_executor'

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
    maintainer='fms',
    maintainer_email='dev@example.com',
    description='Control-PC delivery executor: EMR claim → Nav2 → progress/receipt',
    license='Proprietary',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'executor = delivery_executor.main:main',
        ],
    },
)
