from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as f:
    long_description = f.read()

setup(
    name="airtook_video",
    version="0.0.1",
    description="Daily.co video consult integration for AirTook",
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="Etuken Idung",
    author_email="support@airtook.com",
    packages=find_packages(),
    include_package_data=True,
    install_requires=["requests>=2.31.0"],
)
