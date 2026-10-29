from setuptools import find_packages, setup

package_name = 'vla_calibration'

setup(
    name=package_name,
    version='0.1.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='fastcamp1',
    maintainer_email='leval5716@gmail.com',
    description='Calibration tools: camera intrinsics, block colors, marker-robot frame, wrist grasp check',
    license='Proprietary',
    entry_points={
        'console_scripts': [
            'top_camera = vla_calibration.top_camera:main',
            'wrist_refine = vla_calibration.wrist_refine:main',
        ],
    },
)
