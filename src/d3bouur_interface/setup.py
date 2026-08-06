from setuptools import find_packages, setup

package_name = 'd3bouur_interface'

setup(
    name=package_name,
    version='0.0.1',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
    ],
    install_requires=['setuptools', 'fastapi', 'uvicorn', 'python-multipart', 'markdown'],
    zip_safe=True,
    maintainer='d3bouur',
    maintainer_email='mohamedbani0605@gmail.com',
    description='D3BOUUR screen web interface: FastAPI catalog/events/videos/contact-form UI (browsing mode).',
    license='TODO',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [],
    },
)
