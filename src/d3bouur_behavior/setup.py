from setuptools import find_packages, setup

package_name = 'd3bouur_behavior'

setup(
    name=package_name,
    version='0.0.1',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='d3bouur',
    maintainer_email='mohamedbani0605@gmail.com',
    description='D3BOUUR core behavior state machine: Moving/Mapping, Person Detected, Engaging, with timeout and natural-end resume paths.',
    license='TODO',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [],
    },
)
