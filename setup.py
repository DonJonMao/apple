from setuptools import find_packages, setup

setup(
    name="health-zip-workbench",
    version="0.1.0",
    package_dir={"": "src"},
    packages=find_packages("src"),
    install_requires=["lxml>=4.9"],
    entry_points={"console_scripts": ["healthzip=healthzip.cli:main"]},
)
