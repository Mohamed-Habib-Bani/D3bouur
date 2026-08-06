from setuptools import find_packages, setup

package_name = 'd3bouur_conversation'

setup(
    name=package_name,
    version='0.0.1',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
    ],
    install_requires=['setuptools', 'requests', 'piper-tts', 'beautifulsoup4', 'lxml'],
    zip_safe=True,
    maintainer='d3bouur',
    maintainer_email='mohamedbani0605@gmail.com',
    description='D3BOUUR conversation brain: layered LLM access (OpenRouter primary, local Ollama fallback) with conversation memory.',
    license='TODO',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [],
    },
)
