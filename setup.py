from setuptools import setup, find_packages

if __name__ == "__main__":
    setup(
        name="selectors2",
        description="",
        license="PSFL+MIT",
        url="https://www.github.com/SethMichaelLarson/selectors2",
        version="1.0",
        author="Seth Michael Larson",
        author_email="sethmichaellarson@protonmail.com",
        maintainer="Seth Michael Larson",
        maintainer_email="sethmichaellarson@protonmail.com",
        install_requires=[],
        keywords=['async', 'file', 'socket', 'select', 'backport'],
        py_modules=["selectors2"],
        zip_safe=False,
        classifiers=[
            'Programming Language :: Python :: 2',
            'Programming Language :: Python :: 2.6',
            'Programming Language :: Python :: 2.7',
            'Programming Language :: Python :: 3',
            'Programming Language :: Python :: 3.3',
            'Programming Language :: Python :: 3.4',
            'License :: OSI Approved :: Python Software Foundation License',
            'License :: OSI Approved :: MIT License',
            
            # Fake classifier to prevent accidental releases.
            'Private :: Do Not Upload'
        ]
    )
