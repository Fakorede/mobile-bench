#!/usr/bin/env python3
"""Setup script for mobiledev-bench"""

from setuptools import setup, find_packages

setup(
    name="mobiledev-bench",
    version="0.1.0",
    description="Mobile-Dev app benchmark dataset tools",
    packages=find_packages(),
    python_requires=">=3.8",
    install_requires=[
        "requests",
        "PyGithub",
        "python-dotenv",
    ],
)
