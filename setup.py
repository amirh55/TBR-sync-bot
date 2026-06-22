# -*- coding: utf-8 -*-
from setuptools import setup, find_packages

setup(
    name="tbr-sync-bot",
    version="14.0.0",
    packages=find_packages(),
    install_requires=[
        "python-dotenv==1.0.1",
        "python-telegram-bot==20.8",
        "httpx>=0.26,<1",
    ],
    python_requires=">=3.10",
)
