from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setup(
    name="django-ses-tracking",
    version="3.3.0",
    author="Canusia",
    author_email="info@canusia.com",
    description="Django app for tracking AWS SES email events (bounces, complaints, deliveries)",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/Canusia/package_ses_tracking",
    
    # Package is at root level
    packages=['ses_tracking'],
    package_dir={'ses_tracking': '.'},
    
    # Include files specified in MANIFEST.in
    include_package_data=True,
    
    zip_safe=False,
    
    classifiers=[
        "Development Status :: 4 - Beta",
        "Environment :: Web Environment",
        "Framework :: Django",
        "Framework :: Django :: 3.2",
        "Framework :: Django :: 4.0",
        "Framework :: Django :: 4.1",
        "Framework :: Django :: 4.2",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Programming Language :: Python",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Topic :: Internet :: WWW/HTTP",
        "Topic :: Communications :: Email",
    ],
    
    python_requires=">=3.8",
    
    install_requires=[
        "Django>=3.2",
        "boto3>=1.26.0",
        "python-dateutil>=2.8.0",
        "django-mailer>=2.1",
    ],
)