from setuptools import setup

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setup(
    name="django-ses-tracking",
    version="3.0.3",
    author="Canusia",
    author_email="info@canusia.com",
    description="Django app for tracking AWS SES email events (bounces, complaints, deliveries)",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/Canusia/package_ses_tracking",
    packages=['ses_tracking', 'ses_tracking.migrations', 'ses_tracking.management', 'ses_tracking.management.commands'],
    package_dir={'ses_tracking': '.'},
    package_data={
        'ses_tracking': [
            'templates/ses_tracking/daily_stats/*.html',
            'templates/ses_tracking/bounces_complaints/*.html',
        ],
    },
    include_package_data=True,
    zip_safe=False,
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Framework :: Django",
        "Framework :: Django :: 3.2",
        "Framework :: Django :: 4.0",
        "Framework :: Django :: 4.1",
        "Framework :: Django :: 4.2",
    ],
    python_requires=">=3.8",
    install_requires=[
        "Django>=3.2",
        "boto3>=1.26.0",
        "python-dateutil>=2.8.0",
        "django-mailer>=2.1",
        "djangorestframework>=3.12.0",
    ],
)